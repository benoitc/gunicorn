.. _faq:

===
FAQ
===

WSGI Bits
=========

How do I set SCRIPT_NAME?
-------------------------

By default ``SCRIPT_NAME`` is an empty string. The value could be set by
setting ``SCRIPT_NAME`` in the environment or as an HTTP header. Note that
this headers contains and underscore, so it is only accepted from trusted
forwarders listed in the ``forwarded-allow-ips`` setting.


Server Stuff
============

How do I reload my application in Gunicorn?
-------------------------------------------

You can gracefully reload by sending HUP signal to gunicorn::

    $ kill -HUP masterpid

How might I test a proxy configuration?
---------------------------------------

The Hey_ program is a great way to test that your proxy is correctly
buffering responses for the synchronous workers::

    $ hey -n 10000 -c 100 http://127.0.0.1:5000/

This runs a benchmark of 10000 requests with 100 running concurrently.

How can I name processes?
-------------------------

If you install the Python package setproctitle_ Gunicorn will set the process
names to something a bit more meaningful. This will affect the output you see
in tools like ``ps`` and ``top``. This helps for distinguishing the master
process as well as between masters when running more than one app on a single
machine. See the proc_name_ setting for more information.

Why is there no HTTP Keep-Alive?
--------------------------------

The default Sync workers are designed to run behind Nginx which only uses
HTTP/1.0 with its upstream servers. If you want to deploy Gunicorn to
handle unbuffered requests (ie, serving requests directly from the internet)
you should use one of the async workers.

.. _Hey: https://github.com/rakyll/hey
.. _setproctitle: https://pypi.python.org/pypi/setproctitle
.. _proc_name: settings.html#proc-name


Worker Processes
================

How do I know which type of worker to use?
------------------------------------------

Read the :ref:`design` page for help on the various worker types.

What types of workers are there?
--------------------------------

Check out the configuration docs for worker_class_.

How can I figure out the best number of worker processes?
---------------------------------------------------------

Here is our recommendation for tuning the `number of workers`_.

How can I change the number of workers dynamically?
---------------------------------------------------

TTIN and TTOU signals can be sent to the master to increase or decrease
the number of workers.

To increase the worker count by one::

    $ kill -TTIN $masterpid

To decrease the worker count by one::

    $ kill -TTOU $masterpid

Does Gunicorn suffer from the thundering herd problem?
------------------------------------------------------

The thundering herd problem occurs when many sleeping request handlers, which
may be either threads or processes, wake up at the same time to handle a new
request. Since only one handler will receive the request, the others will have
been awakened for no reason, wasting CPU cycles. At this time, Gunicorn does
not implement any IPC solution for coordinating between worker processes. You
may experience high load due to this problem when using many workers or
threads. However `a work has been started
<https://github.com/benoitc/gunicorn/issues/792>`_ to remove this issue.

.. _worker_class: settings.html#worker-class
.. _`number of workers`: design.html#how-many-workers

Why I don't see any logs in the console?
----------------------------------------

In version 19.0, Gunicorn doesn't log by default in the console.
To watch the logs in the console you need to use the option ``--log-file=-``.
In version 19.2, Gunicorn logs to the console by default again.

Kernel Parameters
=================

When dealing with large numbers of concurrent connections there are a handful
of kernel parameters that you might need to adjust. Generally these should only
affect sites with a very large concurrent load. These parameters are not
specific to Gunicorn, they would apply to any sort of network server you may be
running.

These commands are for Linux. Your particular OS may have slightly different
parameters.

How can I increase the maximum number of file descriptors?
----------------------------------------------------------

One of the first settings that usually needs to be bumped is the maximum number
of open file descriptors for a given process. For the confused out there,
remember that Unices treat sockets as files.

.. warning:: ``sudo ulimit`` may not work

Considering non-privileged users are not able to relax the limit, you should
firstly switch to root user, increase the limit, then run gunicorn. Using ``sudo
ulimit`` would not take effect.

Try systemd's service unit file, or an initscript which runs as root.

How can I increase the maximum socket backlog?
----------------------------------------------

Listening sockets have an associated queue of incoming connections that are
waiting to be accepted. If you happen to have a stampede of clients that fill
up this queue new connections will eventually start getting dropped.

::

    $ sudo sysctl -w net.core.somaxconn="2048"

How can I disable the use of ``sendfile()``
-------------------------------------------

Disabling the use ``sendfile()`` can be done by using the ``--no-sendfile``
setting or by setting the environment variable ``SENDFILE`` to 0.



Troubleshooting
===============

How do I fix Django reporting an ``ImproperlyConfigured`` error?
----------------------------------------------------------------

With asynchronous workers, creating URLs with the ``reverse`` function of
``django.core.urlresolvers`` may fail. Use ``reverse_lazy`` instead.

.. _blocking-os-fchmod:

How do I avoid Gunicorn excessively blocking in ``os.fchmod``?
--------------------------------------------------------------

The current heartbeat system involves calling ``os.fchmod`` on temporary file
handlers and may block a worker for arbitrary time if the directory is on a
disk-backed filesystem. For example, by default ``/tmp`` is not mounted as
``tmpfs`` in Ubuntu; in AWS an EBS root instance volume may sometimes hang for
half a minute and during this time Gunicorn workers may completely block in
``os.fchmod``. ``os.fchmod`` may introduce extra delays if the disk gets full.
Also Gunicorn may refuse to start if it can't create the files when the disk is
full.

Currently to avoid these problems you can use a ``tmpfs`` mount (for a new
directory or for ``/tmp``) and pass its path to ``--worker-tmp-dir``. First,
check whether your ``/tmp`` is disk-backed or RAM-backed::

    $ df /tmp
    Filesystem     1K-blocks    Used Available Use% Mounted on
    /dev/xvda1           ...     ...       ...  ... /

No luck. If you are using Fedora or Ubuntu, you should already have a ``tmpfs``
mount at ``/dev/shm``::

    $ df /dev/shm
    Filesystem     1K-blocks     Used Available Use% Mounted on
    tmpfs                 ...     ...       ...  ... /dev/shm

In this case you can set ``--worker-tmp-dir /dev/shm``, otherwise you can
create a new ``tmpfs`` mount::

    sudo cp /etc/fstab /etc/fstab.orig
    sudo mkdir /mem
    echo 'tmpfs       /mem tmpfs defaults,size=64m,mode=1777,noatime,comment=for-gunicorn 0 0' | sudo tee -a /etc/fstab
    sudo mount /mem

Check the result::

    $ df /mem
    Filesystem     1K-blocks  Used Available Use% Mounted on
    tmpfs              65536     0     65536   0% /mem

Now you can set ``--worker-tmp-dir /mem``.

Why are Workers Silently Killed?
--------------------------------------------------------------

A sometimes subtle problem to debug is when a worker process is killed and there
is little logging information about what happened.

If you use a reverse proxy like NGINX you might see 502 returned to a client.

In the gunicorn logs you might simply see ``[35] [INFO] Booting worker with pid: 35``

It's completely normal for workers to be stop and start, for example due to
max-requests setting. Ordinarily gunicorn will capture any signals and log something.

This particular failure case is usually due to a SIGKILL being received, as it's
not possible to catch this signal silence is usually a common side effect! A common
cause of SIGKILL is when OOM killer terminates a process due to low memory condition.

This is increasingly common in container deployments where memory limits are enforced
by cgroups, you'll usually see evidence of this from dmesg::

    dmesg | grep gunicorn
    Memory cgroup out of memory: Kill process 24534 (gunicorn) score 1506 or sacrifice child
    Killed process 24534 (gunicorn) total-vm:1016648kB, anon-rss:550160kB, file-rss:25824kB, shmem-rss:0kB

In these instances adjusting the memory limit is usually your best bet, it's also possible
to configure OOM not to send SIGKILL by default.
