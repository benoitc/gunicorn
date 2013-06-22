
Settings
========

This is an exhaustive list of settings for Gunicorn. Some settings are only
able to be set from a configuration file. The setting name is what should be
used in the configuration file. The command line arguments are listed as well
for reference on setting at the command line.

Config File
-----------

config
~~~~~~

* ``-c FILE, --config FILE``
* ``gunicorn.conf.py`` if the file exists on the current directory otherwise
  ``None`` is used.

The path to a Gunicorn config file.

Only has an effect when specified on the command line or as part of an
application specific configuration.

Server Socket
-------------

bind
~~~~

* ``-b ADDRESS, --bind ADDRESS``
* ``127.0.0.1:8000``

The socket to bind.

A string of the form: 'HOST', 'HOST:PORT', 'unix:PATH'. An IP is a valid
HOST.

backlog
~~~~~~~

* ``--backlog INT``
* ``2048``

The maximum number of pending connections.

This refers to the number of clients that can be waiting to be served.
Exceeding this number results in the client getting an error when
attempting to connect. It should only affect servers under significant
load.

Must be a positive integer. Generally set in the 64-2048 range.

Worker Processes
----------------

workers
~~~~~~~

* ``-w INT, --workers INT``
* ``1``

The number of worker process for handling requests.

A positive integer generally in the 2-4 x $(NUM_CORES) range. You'll
want to vary this a bit to find the best for your particular
application's work load.

worker_class
~~~~~~~~~~~~

* ``-k STRING, --worker-class STRING``
* ``sync``

The type of workers to use.

The default class (sync) should handle most 'normal' types of workloads.
You'll want to read http://gunicorn.org/design.html for information on
when you might want to choose one of the other worker classes.

A string referring to one of the following bundled classes:

* ``sync``
* ``eventlet`` - Requires eventlet >= 0.9.7
* ``gevent``   - Requires gevent >= 0.12.2 (?)
* ``tornado``  - Requires tornado >= 0.2

Optionally, you can provide your own worker by giving gunicorn a
python path to a subclass of gunicorn.workers.base.Worker. This
alternative syntax will load the gevent class:
``gunicorn.workers.ggevent.GeventWorker``. Alternatively the syntax
can also load the gevent class with ``egg:gunicorn#gevent``

worker_connections
~~~~~~~~~~~~~~~~~~

* ``--worker-connections INT``
* ``1000``

The maximum number of simultaneous clients.

This setting only affects the Eventlet and Gevent worker types.

max_requests
~~~~~~~~~~~~

* ``--max-requests INT``
* ``0``

The maximum number of requests a worker will process before restarting.

Any value greater than zero will limit the number of requests a work
will process before automatically restarting. This is a simple method
to help limit the damage of memory leaks.

If this is set to zero (the default) then the automatic worker
restarts are disabled.

timeout
~~~~~~~

* ``-t INT, --timeout INT``
* ``30``

Workers silent for more than this many seconds are killed and restarted.

Generally set to thirty seconds. Only set this noticeably higher if
you're sure of the repercussions for sync workers. For the non sync
workers it just means that the worker process is still communicating and
is not tied to the length of time required to handle a single request.

graceful_timeout
~~~~~~~~~~~~~~~~

* ``--graceful-timeout INT``
* ``30``

Timeout for graceful workers restart.

Generally set to thirty seconds. How max time worker can handle
request after got restart signal. If the time is up worker will
be force killed.

keepalive
~~~~~~~~~

* ``--keep-alive INT``
* ``2``

The number of seconds to wait for requests on a Keep-Alive connection.

Generally set in the 1-5 seconds range.

Security
--------

limit_request_line
~~~~~~~~~~~~~~~~~~

* ``--limit-request-line INT``
* ``4094``

The maximum size of HTTP request line in bytes.

This parameter is used to limit the allowed size of a client's
HTTP request-line. Since the request-line consists of the HTTP
method, URI, and protocol version, this directive places a
restriction on the length of a request-URI allowed for a request
on the server. A server needs this value to be large enough to
hold any of its resource names, including any information that
might be passed in the query part of a GET request. Value is a number
from 0 (unlimited) to 8190.

This parameter can be used to prevent any DDOS attack.

limit_request_fields
~~~~~~~~~~~~~~~~~~~~

* ``--limit-request-fields INT``
* ``100``

Limit the number of HTTP headers fields in a request.

This parameter is used to limit the number of headers in a request to
prevent DDOS attack. Used with the `limit_request_field_size` it allows
more safety. By default this value is 100 and can't be larger than
32768.

limit_request_field_size
~~~~~~~~~~~~~~~~~~~~~~~~

* ``--limit-request-field_size INT``
* ``8190``

Limit the allowed size of an HTTP request header field.

Value is a number from 0 (unlimited) to 8190. to set the limit
on the allowed size of an HTTP request header field.

Debugging
---------

debug
~~~~~

* ``--debug``
* ``False``

Turn on debugging in the server.

This limits the number of worker processes to 1 and changes some error
handling that's sent to clients.

spew
~~~~

* ``--spew``
* ``False``

Install a trace function that spews every line executed by the server.

This is the nuclear option.

check_config
~~~~~~~~~~~~

* ``--check-config``
* ``False``

Check the configuration..

Server Mechanics
----------------

preload_app
~~~~~~~~~~~

* ``--preload``
* ``False``

Load application code before the worker processes are forked.

By preloading an application you can save some RAM resources as well as
speed up server boot times. Although, if you defer application loading
to each worker process, you can reload your application code easily by
restarting workers.

daemon
~~~~~~

* ``-D, --daemon``
* ``False``

Daemonize the Gunicorn process.

Detaches the server from the controlling terminal and enters the
background.

pidfile
~~~~~~~

* ``-p FILE, --pid FILE``
* ``None``

A filename to use for the PID file.

If not set, no PID file will be written.

user
~~~~

* ``-u USER, --user USER``
* ``501``

Switch worker processes to run as this user.

A valid user id (as an integer) or the name of a user that can be
retrieved with a call to pwd.getpwnam(value) or None to not change
the worker process user.

group
~~~~~

* ``-g GROUP, --group GROUP``
* ``20``

Switch worker process to run as this group.

A valid group id (as an integer) or the name of a user that can be
retrieved with a call to pwd.getgrnam(value) or None to not change
the worker processes group.

umask
~~~~~

* ``-m INT, --umask INT``
* ``0``

A bit mask for the file mode on files written by Gunicorn.

Note that this affects unix socket permissions.

A valid value for the os.umask(mode) call or a string compatible with
int(value, 0) (0 means Python guesses the base, so values like "0",
"0xFF", "0022" are valid for decimal, hex, and octal representations)

tmp_upload_dir
~~~~~~~~~~~~~~

* ``None``

Directory to store temporary request data as they are read.

This may disappear in the near future.

This path should be writable by the process permissions set for Gunicorn
workers. If not specified, Gunicorn will choose a system generated
temporary directory.

secure_scheme_headers
~~~~~~~~~~~~~~~~~~~~~

* ``{'X-FORWARDED-PROTOCOL': 'ssl', 'X-FORWARDED-PROTO': 'https', 'X-FORWARDED-SSL': 'on'}``

A dictionary containing headers and values that the front-end proxy
uses to indicate HTTPS requests. These tell gunicorn to set
wsgi.url_scheme to "https", so your application can tell that the
request is secure.

The dictionary should map upper-case header names to exact string
values. The value comparisons are case-sensitive, unlike the header
names, so make sure they're exactly what your front-end proxy sends
when handling HTTPS requests.

It is important that your front-end proxy configuration ensures that
the headers defined here can not be passed directly from the client.

x_forwarded_for_header
~~~~~~~~~~~~~~~~~~~~~~

* ``X-FORWARDED-FOR``

Set the X-Forwarded-For header that identify the originating IP
address of the client connection to gunicorn via a proxy.

forwarded_allow_ips
~~~~~~~~~~~~~~~~~~~

* ``127.0.0.1``

Front-end's IPs from which allowed to handle X-Forwarded-* headers.
(comma separate).

Logging
-------

accesslog
~~~~~~~~~

* ``--access-logfile FILE``
* ``None``

The Access log file to write to.

"-" means log to stderr.

access_log_format
~~~~~~~~~~~~~~~~~

* ``--access-logformat STRING``
* ``"%(h)s %(l)s %(u)s %(t)s "%(r)s" %(s)s %(b)s "%(f)s" "%(a)s"``

The Access log format .

By default:

%(h)s %(l)s %(u)s %(t)s "%(r)s" %(s)s %(b)s "%(f)s" "%(a)s"


h: remote address
l: '-'
u: currently '-', may be user name in future releases
t: date of the request
r: status line (ex: GET / HTTP/1.1)
s: status
b: response length or '-'
f: referer
a: user agent
T: request time in seconds
D: request time in microseconds,
p: process ID
{Header}i: request header
{Header}o: response header

errorlog
~~~~~~~~

* ``--error-logfile FILE, --log-file FILE``
* ``-``

The Error log file to write to.

"-" means log to stderr.

loglevel
~~~~~~~~

* ``--log-level LEVEL``
* ``info``

The granularity of Error log outputs.

Valid level names are:

* debug
* info
* warning
* error
* critical

logger_class
~~~~~~~~~~~~

* ``--logger-class STRING``
* ``simple``

The logger you want to use to log events in gunicorn.

The default class (``gunicorn.glogging.Logger``) handle most of
normal usages in logging. It provides error and access logging.

You can provide your own worker by giving gunicorn a
python path to a subclass like gunicorn.glogging.Logger.
Alternatively the syntax can also load the Logger class
with `egg:gunicorn#simple`

logconfig
~~~~~~~~~

* ``--log-config FILE``
* ``None``

The log config file to use.
Gunicorn uses the standard Python logging module's Configuration
file format.

Process Naming
--------------

proc_name
~~~~~~~~~

* ``-n STRING, --name STRING``
* ``None``

A base to use with setproctitle for process naming.

This affects things like ``ps`` and ``top``. If you're going to be
running more than one instance of Gunicorn you'll probably want to set a
name to tell them apart. This requires that you install the setproctitle
module.

It defaults to 'gunicorn'.

default_proc_name
~~~~~~~~~~~~~~~~~

* ``gunicorn``

Internal setting that is adjusted for each type of application.

Django
------

django_settings
~~~~~~~~~~~~~~~

* ``--settings STRING``
* ``None``

The Python path to a Django settings module.

e.g. 'myproject.settings.main'. If this isn't provided, the
DJANGO_SETTINGS_MODULE environment variable will be used.

Server Mechanics
----------------

pythonpath
~~~~~~~~~~

* ``--pythonpath STRING``
* ``None``

A directory to add to the Python path for Django.

e.g.
'/home/djangoprojects/myproject'.

Server Hooks
------------

on_starting
~~~~~~~~~~~

*  ::

        def on_starting(server):
            pass

Called just before the master process is initialized.

The callable needs to accept a single instance variable for the Arbiter.

on_reload
~~~~~~~~~

*  ::

        def on_reload(server):
            pass

Called to recycle workers during a reload via SIGHUP.

The callable needs to accept a single instance variable for the Arbiter.

when_ready
~~~~~~~~~~

*  ::

        def when_ready(server):
            pass

Called just after the server is started.

The callable needs to accept a single instance variable for the Arbiter.

pre_fork
~~~~~~~~

*  ::

        def pre_fork(server, worker):
            pass

Called just before a worker is forked.

The callable needs to accept two instance variables for the Arbiter and
new Worker.

post_fork
~~~~~~~~~

*  ::

        def post_fork(server, worker):
            pass

Called just after a worker has been forked.

The callable needs to accept two instance variables for the Arbiter and
new Worker.

post_worker_init
~~~~~~~~~

*  ::

        def post_worker_init(worker):
            pass

Called just after a worker has initialized the application.

The callable needs to accept one instance variable for the initialized
Worker.

pre_exec
~~~~~~~~

*  ::

        def pre_exec(server):
            pass

Called just before a new master process is forked.

The callable needs to accept a single instance variable for the Arbiter.

pre_request
~~~~~~~~~~~

*  ::

        def pre_request(worker, req):
            worker.log.debug("%s %s" % (req.method, req.path))

Called just before a worker processes the request.

The callable needs to accept two instance variables for the Worker and
the Request.

post_request
~~~~~~~~~~~~

*  ::

        def post_request(worker, req, environ):
            pass

Called after a worker processes the request.

The callable needs to accept two instance variables for the Worker and
the Request.

worker_exit
~~~~~~~~~~~

*  ::

        def worker_exit(server, worker):
            pass

Called just after a worker has been exited.

The callable needs to accept two instance variables for the Arbiter and
the just-exited Worker.

Server Mechanics
----------------

proxy_protocol
~~~~~~~~~~~~~~

* ``--proxy-protocol``
* ``False``

Enable detect PROXY protocol (PROXY mode).

Allow using Http and Proxy together. It's may be useful for work with
stunnel as https frondend and gunicorn as http server.

PROXY protocol: http://haproxy.1wt.eu/download/1.5/doc/proxy-protocol.txt

Example for stunnel config::

[https]
protocol = proxy
accept  = 443
connect = 80
cert = /etc/ssl/certs/stunnel.pem
key = /etc/ssl/certs/stunnel.key

proxy_allow_ips
~~~~~~~~~~~~~~~

* ``--proxy-allow-from``
* ``127.0.0.1``

Front-end's IPs from which allowed accept proxy requests (comma separate).

