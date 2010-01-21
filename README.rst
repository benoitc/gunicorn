About
-----

gunicorn 'Green Unicorn' is a WSGI HTTP Server for UNIX, fast clients and nothing else. 

This is a  port of Unicorn (http://unicorn.bogomips.org/) in Python.

Installation
------------

::

    $ python setup.py install

Usage
-----

::

    $ gunicorn --help
    Usage: gunicorn [OPTIONS] APP_MODULE
    
    Options:
      --host=HOST        Host to listen on. [127.0.0.1]
      --port=PORT        Port to listen on. [8000]
      --workers=WORKERS  Number of workers to spawn. [1]
      -h, --help         show this help message and exit


Example with test app::

    $ cd examples
    $ gunicorn --workers=2 test:app
    
    
For django projects use the `gunicorn_django` command::

    $ cd yourdjangoproject
    $ gunicorn_django --workers=2
    
Kernel Parameters
-----------------

There are various kernel parameters that you might want to tune in order to deal with a large number of simulataneous connections. Generally these should only affect sites with a large number of concurrent requests and apply to any sort of network server you may be running. They're listed here for ease of reference.

The commands listed are tested under Mac OS X 10.6. Your flavor of Unix may use slightly different flags. Always reference the appropriate man pages if uncertain.

Increasing the File Descriptor Limit
++++++++++++++++++++++++++++++++++++

One of the first settings that usually needs to be bumped is the maximum number of open file descriptors for a given process. For the confused out there, remember that Unices treat sockets as files.

::
    
    $ sudo ulimit -n 1024

Increasing the Listen Queue Size
++++++++++++++++++++++++++++++++

Listening sockets have an associated queue of incomming connections that are waiting to be accepted. If you happen to have a stampede of clients that fill up this queue new connections will eventually start getting dropped.

::

    $ sudo sysctl -w kern.ipc.somaxconn="1024"

Widening the Ephemeral Port Range
+++++++++++++++++++++++++++++++++

After a socket is closed it eventually enters the TIME_WAIT state. This can become an issue after a prolonged burst of client activity. Eventually the ephemeral port range is used up which can cause new connections to stall while they wait for a valid port.

This setting is generally only required on machines that are being used to test a network server.

::
    
    $ sudo sysctl -w net.inet.ip.portrange.first="8048"

Check `this article`_ for more information on ephemeral ports.

.. _this article: http://www.ncftp.com/ncftpd/doc/misc/ephemeral_ports.html
