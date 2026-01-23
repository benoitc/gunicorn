# Deploying Gunicorn

We strongly recommend running Gunicorn behind a proxy server.

## Nginx configuration

Although many HTTP proxies exist, we recommend [Nginx](https://nginx.org/).
When using the default synchronous workers you must ensure the proxy buffers
slow clients; otherwise Gunicorn becomes vulnerable to denial-of-service
attacks. Use [Hey](https://github.com/rakyll/hey) to verify proxy behaviour.

An example configuration for fast clients with Nginx
([source](https://github.com/benoitc/gunicorn/blob/master/examples/nginx.conf)):

```nginx title="nginx.conf"
--8<-- "examples/nginx.conf"
```



To support streaming requests/responses or patterns such as Comet, long
polling, or WebSockets, disable proxy buffering and run Gunicorn with an async
worker class:

```nginx
location @proxy_to_app {
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header Host $http_host;
    proxy_redirect off;
    proxy_buffering off;

    proxy_pass http://app_server;
}
```

To ignore aborted requests (for example, health checks that close connections
prematurely) enable
[`proxy_ignore_client_abort`](http://nginx.org/en/docs/http/ngx_http_proxy_module.html#proxy_ignore_client_abort):

```nginx
proxy_ignore_client_abort on;
```

!!! note
    The default value for `proxy_ignore_client_abort` is `off`. If it remains off
    Nginx logs will report error 499 and Gunicorn may log `Ignoring EPIPE` when the
    log level is `debug`.



Pass protocol information to Gunicorn so applications can generate correct
URLs. Add this header to your `location` block:

```nginx
proxy_set_header X-Forwarded-Proto $scheme;
```

If Nginx runs on a different host, tell Gunicorn which proxies are trusted so it
accepts the `X-Forwarded-*` headers:

```bash
gunicorn -w 3 --forwarded-allow-ips="10.170.3.217,10.170.3.220" test:app
```

When all traffic comes from trusted proxies (for example Heroku) you can set
`--forwarded-allow-ips='*'`. This is **dangerous** if untrusted clients can
reach Gunicorn directly, because forged headers could make your application
serve secure content over plain HTTP.

Gunicorn 19 changed the handling of `REMOTE_ADDR` to conform to
[RFC 3875](https://www.rfc-editor.org/rfc/rfc3875), meaning it now records the
proxy IP rather than the upstream client. To log the real client address, set
[`access_log_format`](reference/settings.md#access_log_format) to include `X-Forwarded-For`:

```text
%({x-forwarded-for}i)s %(l.md)s %(u.md)s %(t.md)s "%(r.md)s" %(s.md)s %(b.md)s "%(f.md)s" "%(a.md)s"
```

When binding Gunicorn to a UNIX socket `REMOTE_ADDR` will be empty.

## Using virtual environments

Install Gunicorn inside your project
[virtual environment](https://pypi.python.org/pypi/virtualenv) to keep versions
isolated:

```bash
mkdir ~/venvs/
virtualenv ~/venvs/webapp
source ~/venvs/webapp/bin/activate
pip install gunicorn
deactivate
```

Force installation into the active virtual environment with `--ignore-installed`:

```bash
source ~/venvs/webapp/bin/activate
pip install -I gunicorn
```

## Monitoring

!!! note
    Do not enable Gunicorn's daemon mode when using process monitors. These
    supervisors expect to manage the direct child process.



### Gaffer

Use [Gaffer](https://gaffer.readthedocs.io/) with *gafferd* to manage Gunicorn:

```ini
[process:gunicorn]
cmd = gunicorn -w 3 test:app
cwd = /path/to/project
```

Create a `Procfile` if you prefer:

```procfile
gunicorn = gunicorn -w 3 test:app
```

Start Gunicorn via Gaffer:

```bash
gaffer start
```

Or load it into a running *gafferd* instance:

```bash
gaffer load
```

### runit

[runit](http://smarden.org/runit/) is a popular supervisor. A sample service
script (see the
[full example](https://github.com/benoitc/gunicorn/blob/master/examples/gunicorn_rc)):

```bash
#!/bin/sh

GUNICORN=/usr/local/bin/gunicorn
ROOT=/path/to/project
PID=/var/run/gunicorn.pid

APP=main:application

if [ -f $PID ]; then rm $PID; fi

cd $ROOT
exec $GUNICORN -c $ROOT/gunicorn.conf.py --pid=$PID $APP
```

Save as `/etc/sv/<app_name>/run`, make it executable, and symlink into
`/etc/service/<app_name>`. runit will then supervise Gunicorn.

### Supervisor

[Supervisor](http://supervisord.org/) configuration example (adapted from
[examples/supervisor.conf](https://github.com/benoitc/gunicorn/blob/master/examples/supervisor.conf)):

```ini
[program:gunicorn]
command=/path/to/gunicorn main:application -c /path/to/gunicorn.conf.py
directory=/path/to/project
user=nobody
autostart=true
autorestart=true
redirect_stderr=true
```

### Upstart

Sample Upstart config (logs go to `/var/log/upstart/myapp.log`):

```upstart
# /etc/init/myapp.conf

description "myapp"

start on (filesystem.md)
stop on runlevel [016]

respawn
setuid nobody
setgid nogroup
chdir /path/to/app/directory

exec /path/to/virtualenv/bin/gunicorn myapp:app
```

### systemd

[systemd](https://www.freedesktop.org/wiki/Software/systemd/) can create a UNIX
socket and launch Gunicorn on demand.

Service file:

```ini
# /etc/systemd/system/gunicorn.service

[Unit]
Description=gunicorn daemon
Requires=gunicorn.socket
After=network.target

[Service]
Type=notify
NotifyAccess=main
User=someuser
Group=someuser
WorkingDirectory=/home/someuser/applicationroot
ExecStart=/usr/bin/gunicorn applicationname.wsgi
ExecReload=/bin/kill -s HUP $MAINPID
KillMode=mixed
TimeoutStopSec=5
PrivateTmp=true

[Install]
WantedBy=multi-user.target
```

`Type=notify` lets Gunicorn report readiness to systemd. If the service should
run under a transient user consider adding `DynamicUser=true`. Tighten
permissions further with `ProtectSystem=strict` if the app permits.

Socket activation file:

```ini
# /etc/systemd/system/gunicorn.socket

[Unit]
Description=gunicorn socket

[Socket]
ListenStream=/run/gunicorn.sock
SocketUser=www-data
SocketGroup=www-data
SocketMode=0660

[Install]
WantedBy=sockets.target
```

Enable and start the socket so it begins listening immediately and on reboot:

```bash
systemctl enable --now gunicorn.socket
```

Test connectivity from the nginx user (Debian defaults to `www-data`):

```bash
sudo -u www-data curl --unix-socket /run/gunicorn.sock http
```

!!! note
    Use `systemctl show --value -p MainPID gunicorn.service` to retrieve the main
    process ID or `systemctl kill -s HUP gunicorn.service` to send signals.



Configure Nginx to proxy to the new socket:

```nginx
user www-data;
...
http {
    server {
        listen          8000;
        server_name     127.0.0.1;
        location / {
            proxy_pass http://unix:/run/gunicorn.sock;
        }
    }
}
...
```

!!! note
    Adjust `listen` and `server_name` for production (typically port 80 and your
    site's domain).



Ensure nginx starts automatically:

```bash
systemctl enable nginx.service
systemctl start nginx
```

Browse to <http://127.0.0.1:8000/> to verify Gunicorn + Nginx + systemd.

## Logging

Configure logging through the CLI flags described in the
[settings documentation](reference/settings.md#logging) or via a
[logging configuration file](https://github.com/benoitc/gunicorn/blob/master/examples/logging.conf).
Rotate logs with `logrotate` by sending `SIGUSR1`:

```bash
kill -USR1 $(cat /var/run/gunicorn.pid)
```

!!! note
    If you override the `LOGGING` dictionary, set `disable_existing_loggers` to
    `False` so Gunicorn's loggers remain active.



!!! warning
    Gunicorn's error log should capture Gunicorn-related messages only. Route your
    application logs separately.


