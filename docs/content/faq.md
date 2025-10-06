<span id="faq"></span>
# FAQ

## WSGI bits

### How do I set `SCRIPT_NAME`?

By default `SCRIPT_NAME` is an empty string. Set it via an environment variable
or HTTP header. Because the header contains an underscore it is only accepted
from trusted forwarders listed in [`forwarded_allow_ips`](reference/settings.md#forwarded_allow_ips).

!!! note
    If your application should appear under a subfolder, `SCRIPT_NAME` typically
    starts with a single leading slash and no trailing slash.



## Server stuff

### How do I reload my application in Gunicorn?

Send `HUP` to the master process for a graceful reload:

```bash
kill -HUP masterpid
```

### How might I test a proxy configuration?

Use [Hey](https://github.com/rakyll/hey) to confirm that your proxy buffers
responses correctly for synchronous workers:

```bash
hey -n 10000 -c 100 http://127.0.0.1:5000/
```

That benchmark issues 10,000 requests with a concurrency of 100.

### How can I name processes?

Install [setproctitle](https://pypi.python.org/pypi/setproctitle) to give
Gunicorn processes meaningful names in tools such as `ps` and `top`. This helps
when running multiple Gunicorn instances. See the
[`proc_name`](reference/settings.md#proc_name) setting for details.

### Why is there no HTTP keep-alive?

The default sync workers target Nginx, which uses HTTP/1.0 for upstream
connections. If you need to serve unbuffered internet traffic directly, pick an
async worker instead.

## Worker processes

### How do I know which type of worker to use?

Read the [design guide](design.md) for guidance on worker types.

### What types of workers are available?

See the [`worker_class`](reference/settings.md#worker_class) configuration reference.

### How can I figure out the best number of worker processes?

Follow the recommendations for tuning the [`number of workers`](design.md#how-many-workers).

### How can I change the number of workers dynamically?

Send `TTIN` or `TTOU` to the master process:

```bash
kill -TTIN $masterpid  # increment workers
kill -TTOU $masterpid  # decrement workers
```

### Does Gunicorn suffer from the thundering herd problem?

Potentially, when many sleeping handlers wake simultaneously but only one takes
the request. There is ongoing work to mitigate this
([issue #792](https://github.com/benoitc/gunicorn/issues/792)). Monitor load if
you use large numbers of workers or threads.

### Why don't I see logs in the console?

Gunicorn 19.0 disabled console logging by default. Use `--log-file=-` to stream
logs to stdout. Console logging returned in 19.2.

## Kernel parameters

High-concurrency deployments may need kernel tuning. These Linux-oriented tips
apply to any network service.

### How can I increase the maximum number of file descriptors?

Raise the per-process limit (remember sockets count as files). Running `sudo
ulimit` is ineffective—switch to root, adjust the limit, then launch Gunicorn.
Consider managing limits via systemd service units or init scripts.

### How can I increase the maximum socket backlog?

Increase the queue of pending connections:

```bash
sudo sysctl -w net.core.somaxconn="2048"
```

### How can I disable the use of `sendfile()`?

Pass `--no-sendfile` or set the `SENDFILE=0` environment variable.

## Troubleshooting

### Django reports `ImproperlyConfigured`

Asynchronous workers may break `django.core.urlresolvers.reverse`. Use
`reverse_lazy` instead.

### How do I avoid blocking in `os.fchmod`?

Gunicorn's heartbeat touches temporary files. On disk-backed filesystems (for
example `/tmp` on some distributions) `os.fchmod` can block if I/O stalls or the
filesystem fills up. Mount a `tmpfs` and point `--worker-tmp-dir` to it.

Check whether `/tmp` is RAM-backed:

```bash
df /tmp
```

If not, create a new `tmpfs` mount:

```bash
sudo cp /etc/fstab /etc/fstab.orig
sudo mkdir /mem
echo 'tmpfs       /mem tmpfs defaults,size=64m,mode=1777,noatime,comment=for-gunicorn 0 0' | sudo tee -a /etc/fstab
sudo mount /mem
```

Verify the result:

```bash
df /mem
```

Then start Gunicorn with `--worker-tmp-dir /mem`.

### Why are workers silently killed?

If a worker vanishes without logs, check for `SIGKILL`. Reverse proxies may show
`502` responses while Gunicorn logs only new worker startups (for example,
`[INFO] Booting worker`). A common culprit is the OOM killer in cgroups-limited
environments.

Inspect kernel logs:

```bash
dmesg | grep gunicorn
```

If you see messages similar to `Memory cgroup out of memory ... Killed process
(gunicorn.md)`, raise memory limits or adjust OOM behaviour.
