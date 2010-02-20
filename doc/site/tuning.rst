template: doc.html
title: Tuning

Tuning
======

Unicorn Configuration
---------------------

DO NOT scale the number of workers to the number of clients you expect to have. Gunicorn should only need 4-12 worker processes to handle hundreds or thousands of simultaneous clients. Remember, Gunicorn is **NOT** designed for serving slow clients, that's the job of Nginx_.

See Configuration_ for a more thorough description of the available parameters.

.. _Nginx: http://www.nginx.org
.. _Configuration: configuration.html

Kernel Parameters
-----------------

When dealing with large numbers of concurrent connections there are a handful of kernel parameters that you might need to adjust. Generally these should only affect sites with a very large concurrent load. These parameters are not specific to Gunicorn, they would apply to any sort of network server you may be running.

The commands listed are tested under Mac OS X 10.6. Your flavor of Unix may use slightly different flags. Always reference the appropriate man pages if uncertain.

File Descriptor Limits
++++++++++++++++++++++

One of the first settings that usually needs to be bumped is the maximum number of open file descriptors for a given process. For the confused out there, remember that Unices treat sockets as files.

::
    
    $ sudo ulimit -n 2048

Listen Queue Size
+++++++++++++++++

Listening sockets have an associated queue of incoming connections that are waiting to be accepted. If you happen to have a stampede of clients that fill up this queue new connections will eventually start getting dropped.

::

    $ sudo sysctl -w kern.ipc.somaxconn="2048"

Ephemeral Port Range
++++++++++++++++++++

After a socket is closed it enters the TIME_WAIT state. This can become an issue after a prolonged burst of client activity. Eventually the ephemeral port range is exhausted which can cause new connections to stall while they wait for a valid port.

This setting is generally only required on machines that are being used to test a network server.

::

    $ sudo sysctl -w net.inet.ip.portrange.first="8048"
