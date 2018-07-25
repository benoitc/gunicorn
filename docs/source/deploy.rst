==================
Deploying Gunicorn
==================

We strongly recommend to use Gunicorn behind a proxy server.

Nginx Configuration
===================

Although there are many HTTP proxies available, we strongly advise that you
use Nginx_. If you choose another proxy server you need to make sure that it
buffers slow clients when you use default Gunicorn workers. Without this
buffering Gunicorn will be easily susceptible to denial-of-service attacks.
You can use Hey_ to check if your proxy is behaving properly.

An `example configuration`_ file for fast clients with Nginx_:

.. literalinclude:: ../../examples/nginx.conf
   :language: nginx
   :caption: **nginx.conf**

If you want to be able to handle streaming request/responses or other fancy
features like Comet, Long polling, or Web sockets, you need to turn off the
proxy buffering. **When you do this** you must run with one of the async worker
classes.

To turn off buffering, you only need to add ``proxy_buffering off;`` to your
``location`` block::

  ...
  location @proxy_to_app {
      proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
      proxy_set_header Host $http_host;
      proxy_redirect off;
      proxy_buffering off;

      proxy_pass http://app_server;
  }
  ...

It is recommended to pass protocol information to Gunicorn. Many web
frameworks use this information to generate URLs. Without this
information, the application may mistakenly generate 'http' URLs in
'https' responses, leading to mixed content warnings or broken
applications. To configure Nginx to pass an appropriate header, add
a ``proxy_set_header`` directive to your ``location`` block::

    ...
    proxy_set_header X-Forwarded-Proto $scheme;
    ...

If you are running Nginx on a different host than Gunicorn you need to tell
Gunicorn to trust the ``X-Forwarded-*`` headers sent by Nginx. By default,
Gunicorn will only trust these headers if the connection comes from localhost.
This is to prevent a malicious client from forging these headers::

    $ gunicorn -w 3 --forwarded-allow-ips="10.170.3.217,10.170.3.220" test:app

When the Gunicorn host is completely firewalled from the external network such
that all connections come from a trusted proxy (e.g. Heroku) this value can
be set to '*'. Using this value is **potentially dangerous** if connections to
Gunicorn may come from untrusted proxies or directly from clients since the
application may be tricked into serving SSL-only content over an insecure
connection.

Gunicorn 19 introduced a breaking change concerning how ``REMOTE_ADDR`` is
handled. Previous to Gunicorn 19 this was set to the value of
``X-Forwarded-For`` if received from a trusted proxy. However, this was not in
compliance with :rfc:`3875` which is why the ``REMOTE_ADDR`` is now the IP
address of **the proxy** and **not the actual user**. You should instead
configure Nginx to send the user's IP address through the ``X-Forwarded-For``
header like this::

    ...
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    ...

It is also worth noting that the ``REMOTE_ADDR`` will be completely empty if
you bind Gunicorn to a UNIX socket and not a TCP ``host:port`` tuple.

Using Virtualenv
================

To serve an app from a Virtualenv_ it is generally easiest to just install
Gunicorn directly into the Virtualenv. This will create a set of Gunicorn
scripts for that Virtualenv which can be used to run applications normally.

If you have Virtualenv installed, you should be able to do something like
this::

    $ mkdir ~/venvs/
    $ virtualenv ~/venvs/webapp
    $ source ~/venvs/webapp/bin/activate
    $ pip install gunicorn
    $ deactivate

Then you just need to use one of the three Gunicorn scripts that was installed
into ``~/venvs/webapp/bin``.

Note: You can force the installation of Gunicorn in your Virtualenv by
passing ``-I`` or ``--ignore-installed`` option to pip::

     $ source ~/venvs/webapp/bin/activate
     $ pip install -I gunicorn

Monitoring
==========

.. note::
   Make sure that when using either of these service monitors you do not
   enable the Gunicorn's daemon mode. These monitors expect that the process
   they launch will be the process they need to monitor. Daemonizing will
   fork-exec which creates an unmonitored process and generally just
   confuses the monitor services.

Gaffer
------

Using Gafferd and gaffer
++++++++++++++++++++++++

Gaffer_ can be used to monitor Gunicorn. A simple configuration is::

    [process:gunicorn]
    cmd = gunicorn -w 3 test:app
    cwd = /path/to/project

Then you can easily manage Gunicorn using Gaffer_.


Using a Procfile
++++++++++++++++

Create a ``Procfile`` in your project::

    gunicorn = gunicorn -w 3 test:app

You can launch any other applications that should be launched at the same time.

Then you can start your Gunicorn application using Gaffer_::

    gaffer start

If gafferd is launched you can also load your Procfile in it directly::

    gaffer load

All your applications will be then supervised by gafferd.

Runit
-----

A popular method for deploying Gunicorn is to have it monitored by runit_.
Here is an `example service`_ definition::

    #!/bin/sh

    GUNICORN=/usr/local/bin/gunicorn
    ROOT=/path/to/project
    PID=/var/run/gunicorn.pid

    APP=main:application

    if [ -f $PID ]; then rm $PID; fi

    cd $ROOT
    exec $GUNICORN -c $ROOT/gunicorn.conf.py --pid=$PID $APP

Save this as ``/etc/sv/[app_name]/run``, and make it executable
(``chmod u+x /etc/sv/[app_name]/run``).
Then run ``ln -s /etc/sv/[app_name] /etc/service/[app_name]``.
If runit is installed, Gunicorn should start running automatically as soon
as you create the symlink.

If it doesn't start automatically, run the script directly to troubleshoot.

Supervisor
----------

Another useful tool to monitor and control Gunicorn is Supervisor_. A
`simple configuration`_ is::

    [program:gunicorn]
    command=/path/to/gunicorn main:application -c /path/to/gunicorn.conf.py
    directory=/path/to/project
    user=nobody
    autostart=true
    autorestart=true
    redirect_stderr=true

Upstart
-------

Using Gunicorn with upstart is simple. In this example we will run the app
"myapp" from a virtualenv. All errors will go to
``/var/log/upstart/myapp.log``.

**/etc/init/myapp.conf**::

    description "myapp"

    start on (filesystem)
    stop on runlevel [016]

    respawn
    setuid nobody
    setgid nogroup
    chdir /path/to/app/directory

    exec /path/to/virtualenv/bin/gunicorn myapp:app

Systemd
-------

A tool that is starting to be common on linux systems is Systemd_. Below are
configurations files and instructions for using systemd to create a unix socket
for incoming Gunicorn requests.  Systemd will listen on this socket and start
gunicorn automatically in response to traffic.  Later in this section are 
instructions for configuring Nginx to forward web traffic to the newly created
unix socket:

**/etc/systemd/system/gunicorn.service**::

    [Unit]
    Description=gunicorn daemon
    Requires=gunicorn.socket
    After=network.target

    [Service]
    PIDFile=/run/gunicorn/pid
    User=someuser
    Group=someuser
    RuntimeDirectory=gunicorn
    WorkingDirectory=/home/someuser/applicationroot
    ExecStart=/usr/bin/gunicorn --pid /run/gunicorn/pid   \
              --bind unix:/run/gunicorn/socket applicationname.wsgi
    ExecReload=/bin/kill -s HUP $MAINPID
    ExecStop=/bin/kill -s TERM $MAINPID
    PrivateTmp=true

    [Install]
    WantedBy=multi-user.target

**/etc/systemd/system/gunicorn.socket**::

    [Unit]
    Description=gunicorn socket

    [Socket]
    ListenStream=/run/gunicorn/socket

    [Install]
    WantedBy=sockets.target

**/etc/tmpfiles.d/gunicorn.conf**::

    d /run/gunicorn 0755 someuser somegroup -

Next enable the socket so it autostarts at boot::

    systemctl enable gunicorn.socket

Either reboot, or start the services manually::

    systemctl start gunicorn.socket


After running ``curl --unix-socket /run/gunicorn/socket http``, Gunicorn
should start and you should see some HTML from your server in the terminal.

You must now configure your web proxy to send traffic to the new Gunicorn
socket. Edit your ``nginx.conf`` to include the following:

**/etc/nginx/nginx.conf**::

    ...
    http {
        server {
            listen          8000;
            server_name     127.0.0.1;
            location / {
                proxy_pass http://unix:/run/gunicorn/socket;
            }
        }
    }
    ...

.. note::

    The listen and server_name used here are configured for a local machine.
    In a production server you will most likely listen on port 80,
    and use your URL as the server_name.
    
Now make sure you enable the nginx service so it automatically starts at boot::

    systemctl enable nginx.service
    
Either reboot, or start Nginx with the following command::

    systemctl start nginx
    
Now you should be able to test Nginx with Gunicorn by visiting
http://127.0.0.1:8000/ in any web browser. Systemd is now set up.


Logging
=======

Logging can be configured by using various flags detailed in the
`configuration documentation`_ or by creating a `logging configuration file`_.
Send the ``USR1`` signal to rotate logs if you are using the logrotate
utility::

    kill -USR1 $(cat /var/run/gunicorn.pid)

.. note::
   Overriding the ``LOGGING`` dictionary requires to set
   ``disable_existing_loggers: False`` to not interfere with the Gunicorn
   logging.

.. warning::
   Gunicorn error log is here to log errors from Gunicorn, not from another
   application.

.. _Nginx: https://nginx.org/
.. _Hey: https://github.com/rakyll/hey
.. _`example configuration`: https://github.com/benoitc/gunicorn/blob/master/examples/nginx.conf
.. _runit: http://smarden.org/runit/
.. _`example service`: https://github.com/benoitc/gunicorn/blob/master/examples/gunicorn_rc
.. _Supervisor: http://supervisord.org/
.. _`simple configuration`: https://github.com/benoitc/gunicorn/blob/master/examples/supervisor.conf
.. _`configuration documentation`: http://docs.gunicorn.org/en/latest/settings.html#logging
.. _`logging configuration file`: https://github.com/benoitc/gunicorn/blob/master/examples/logging.conf
.. _Virtualenv: https://pypi.python.org/pypi/virtualenv
.. _Systemd: https://www.freedesktop.org/wiki/Software/systemd/
.. _Gaffer: https://gaffer.readthedocs.io/
