.. Please update gunicorn/config.py instead.

.. _settings:

Settings
========

This is an exhaustive list of settings for Gunicorn. Some settings are only
able to be set from a configuration file. The setting name is what should be
used in the configuration file. The command line arguments are listed as well
for reference on setting at the command line.

.. note::

    Settings can be specified by using environment variable
    ``GUNICORN_CMD_ARGS``. All available command line arguments can be used.
    For example, to specify the bind address and number of workers::

        $ GUNICORN_CMD_ARGS="--bind=127.0.0.1 --workers=3" gunicorn app:app

    .. versionadded:: 19.7

Config File
-----------

.. _config:

``config``
~~~~~~~~~~

**Command line:** ``-c CONFIG`` or ``--config CONFIG``

**Default:** ``'./gunicorn.conf.py'``

The Gunicorn config file.

A string of the form ``PATH``, ``file:PATH``, or ``python:MODULE_NAME``.

Only has an effect when specified on the command line or as part of an
application specific configuration.

By default, a file named ``gunicorn.conf.py`` will be read from the same
directory where gunicorn is being run.

.. versionchanged:: 19.4
   Loading the config from a Python module requires the ``python:``
   prefix.

.. _wsgi-app:

``wsgi_app``
~~~~~~~~~~~~

**Default:** ``None``

A WSGI application path in pattern ``$(MODULE_NAME):$(VARIABLE_NAME)``.

.. versionadded:: 20.1.0

Debugging
---------

.. _reload:

``reload``
~~~~~~~~~~

**Command line:** ``--reload``

**Default:** ``False``

Restart workers when code changes.

This setting is intended for development. It will cause workers to be
restarted whenever application code changes.

The reloader is incompatible with application preloading. When using a
paste configuration be sure that the server block does not import any
application code or the reload will not work as designed.

The default behavior is to attempt inotify with a fallback to file
system polling. Generally, inotify should be preferred if available
because it consumes less system resources.

.. note::
   In order to use the inotify reloader, you must have the ``inotify``
   package installed.

.. _reload-engine:

``reload_engine``
~~~~~~~~~~~~~~~~~

**Command line:** ``--reload-engine STRING``

**Default:** ``'auto'``

The implementation that should be used to power :ref:`reload`.

Valid engines are:

* ``'auto'``
* ``'poll'``
* ``'inotify'`` (requires inotify)

.. versionadded:: 19.7

.. _reload-extra-files:

``reload_extra_files``
~~~~~~~~~~~~~~~~~~~~~~

**Command line:** ``--reload-extra-file FILES``

**Default:** ``[]``

Extends :ref:`reload` option to also watch and reload on additional files
(e.g., templates, configurations, specifications, etc.).

.. versionadded:: 19.8

.. _spew:

``spew``
~~~~~~~~

**Command line:** ``--spew``

**Default:** ``False``

Install a trace function that spews every line executed by the server.

This is the nuclear option.

.. _check-config:

``check_config``
~~~~~~~~~~~~~~~~

**Command line:** ``--check-config``

**Default:** ``False``

Check the configuration and exit. The exit status is 0 if the
configuration is correct, and 1 if the configuration is incorrect.

.. _print-config:

``print_config``
~~~~~~~~~~~~~~~~

**Command line:** ``--print-config``

**Default:** ``False``

Print the configuration settings as fully resolved. Implies :ref:`check-config`.

Logging
-------

.. _accesslog:

``accesslog``
~~~~~~~~~~~~~

**Command line:** ``--access-logfile FILE``

**Default:** ``None``

The Access log file to write to.

``'-'`` means log to stdout.

.. _disable-redirect-access-to-syslog:

``disable_redirect_access_to_syslog``
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

**Command line:** ``--disable-redirect-access-to-syslog``

**Default:** ``False``

Disable redirect access logs to syslog.

.. versionadded:: 19.8

.. _access-log-format:

``access_log_format``
~~~~~~~~~~~~~~~~~~~~~

**Command line:** ``--access-logformat STRING``

**Default:** ``'%(h)s %(l)s %(u)s %(t)s "%(r)s" %(s)s %(b)s "%(f)s" "%(a)s"'``

The access log format.

===========  ===========
Identifier   Description
===========  ===========
h            remote address
l            ``'-'``
u            user name
t            date of the request
r            status line (e.g. ``GET / HTTP/1.1``)
m            request method
U            URL path without query string
q            query string
H            protocol
s            status
B            response length
b            response length or ``'-'`` (CLF format)
f            referer
a            user agent
T            request time in seconds
M            request time in milliseconds
D            request time in microseconds
L            request time in decimal seconds
p            process ID
{header}i    request header
{header}o    response header
{variable}e  environment variable
===========  ===========

Use lowercase for header and environment variable names, and put
``{...}x`` names inside ``%(...)s``. For example::

    %({x-forwarded-for}i)s

.. _errorlog:

``errorlog``
~~~~~~~~~~~~

**Command line:** ``--error-logfile FILE`` or ``--log-file FILE``

**Default:** ``'-'``

The Error log file to write to.

Using ``'-'`` for FILE makes gunicorn log to stderr.

.. versionchanged:: 19.2
   Log to stderr by default.

.. _loglevel:

``loglevel``
~~~~~~~~~~~~

**Command line:** ``--log-level LEVEL``

**Default:** ``'info'``

The granularity of Error log outputs.

Valid level names are:

* ``'debug'``
* ``'info'``
* ``'warning'``
* ``'error'``
* ``'critical'``

.. _capture-output:

``capture_output``
~~~~~~~~~~~~~~~~~~

**Command line:** ``--capture-output``

**Default:** ``False``

Redirect stdout/stderr to specified file in :ref:`errorlog`.

.. versionadded:: 19.6

.. _logger-class:

``logger_class``
~~~~~~~~~~~~~~~~

**Command line:** ``--logger-class STRING``

**Default:** ``'gunicorn.glogging.Logger'``

The logger you want to use to log events in Gunicorn.

The default class (``gunicorn.glogging.Logger``) handles most
normal usages in logging. It provides error and access logging.

You can provide your own logger by giving Gunicorn a Python path to a
class that quacks like ``gunicorn.glogging.Logger``.

.. _logconfig:

``logconfig``
~~~~~~~~~~~~~

**Command line:** ``--log-config FILE``

**Default:** ``None``

The log config file to use.
Gunicorn uses the standard Python logging module's Configuration
file format.

.. _logconfig-json:

logiconfig_json
~~~~~~~~~

* ``--log-config-json FILE``
* ``None``

The log config file written in JSON.

.. _logconfig-dict:

``logconfig_dict``
~~~~~~~~~~~~~~~~~~

**Command line:** ``--log-config-dict``

**Default:** ``{}``

The log config dictionary to use, using the standard Python
logging module's dictionary configuration format. This option
takes precedence over the :ref:`logconfig` and :ref:`logConfigJson` options, which uses the
older file configuration format and JSON respectively.


Format: https://docs.python.org/3/library/logging.config.html#logging.config.dictConfig

For more context you can look at the default configuration dictionary for logging, which can be found at ``gunicorn.glogging.CONFIG_DEFAULTS``.

.. versionadded:: 19.8

.. _syslog-addr:

``syslog_addr``
~~~~~~~~~~~~~~~

**Command line:** ``--log-syslog-to SYSLOG_ADDR``

**Default:** ``'unix:///var/run/syslog'``

Address to send syslog messages.

Address is a string of the form:

* ``unix://PATH#TYPE`` : for unix domain socket. ``TYPE`` can be ``stream``
  for the stream driver or ``dgram`` for the dgram driver.
  ``stream`` is the default.
* ``udp://HOST:PORT`` : for UDP sockets
* ``tcp://HOST:PORT`` : for TCP sockets

.. _syslog:

``syslog``
~~~~~~~~~~

**Command line:** ``--log-syslog``

**Default:** ``False``

Send *Gunicorn* logs to syslog.

.. versionchanged:: 19.8
   You can now disable sending access logs by using the
   :ref:`disable-redirect-access-to-syslog` setting.

.. _syslog-prefix:

``syslog_prefix``
~~~~~~~~~~~~~~~~~

**Command line:** ``--log-syslog-prefix SYSLOG_PREFIX``

**Default:** ``None``

Makes Gunicorn use the parameter as program-name in the syslog entries.

All entries will be prefixed by ``gunicorn.<prefix>``. By default the
program name is the name of the process.

.. _syslog-facility:

``syslog_facility``
~~~~~~~~~~~~~~~~~~~

**Command line:** ``--log-syslog-facility SYSLOG_FACILITY``

**Default:** ``'user'``

Syslog facility name

.. _enable-stdio-inheritance:

``enable_stdio_inheritance``
~~~~~~~~~~~~~~~~~~~~~~~~~~~~

**Command line:** ``-R`` or ``--enable-stdio-inheritance``

**Default:** ``False``

Enable stdio inheritance.

Enable inheritance for stdio file descriptors in daemon mode.

Note: To disable the Python stdout buffering, you can to set the user
environment variable ``PYTHONUNBUFFERED`` .

.. _statsd-host:

``statsd_host``
~~~~~~~~~~~~~~~

**Command line:** ``--statsd-host STATSD_ADDR``

**Default:** ``None``

The address of the StatsD server to log to.

Address is a string of the form:

* ``unix://PATH`` : for a unix domain socket.
* ``HOST:PORT`` : for a network address

.. versionadded:: 19.1

.. _dogstatsd-tags:

``dogstatsd_tags``
~~~~~~~~~~~~~~~~~~

**Command line:** ``--dogstatsd-tags DOGSTATSD_TAGS``

**Default:** ``''``

A comma-delimited list of datadog statsd (dogstatsd) tags to append to
statsd metrics.

.. versionadded:: 20

.. _statsd-prefix:

``statsd_prefix``
~~~~~~~~~~~~~~~~~

**Command line:** ``--statsd-prefix STATSD_PREFIX``

**Default:** ``''``

Prefix to use when emitting statsd metrics (a trailing ``.`` is added,
if not provided).

.. versionadded:: 19.2

Process Naming
--------------

.. _proc-name:

``proc_name``
~~~~~~~~~~~~~

**Command line:** ``-n STRING`` or ``--name STRING``

**Default:** ``None``

A base to use with setproctitle for process naming.

This affects things like ``ps`` and ``top``. If you're going to be
running more than one instance of Gunicorn you'll probably want to set a
name to tell them apart. This requires that you install the setproctitle
module.

If not set, the *default_proc_name* setting will be used.

.. _default-proc-name:

``default_proc_name``
~~~~~~~~~~~~~~~~~~~~~

**Default:** ``'gunicorn'``

Internal setting that is adjusted for each type of application.

SSL
---

.. _keyfile:

``keyfile``
~~~~~~~~~~~

**Command line:** ``--keyfile FILE``

**Default:** ``None``

SSL key file

.. _certfile:

``certfile``
~~~~~~~~~~~~

**Command line:** ``--certfile FILE``

**Default:** ``None``

SSL certificate file

.. _ssl-version:

``ssl_version``
~~~~~~~~~~~~~~~

**Command line:** ``--ssl-version``

**Default:** ``<_SSLMethod.PROTOCOL_TLS: 2>``

SSL version to use.

============= ============
--ssl-version Description
============= ============
SSLv3         SSLv3 is not-secure and is strongly discouraged.
SSLv23        Alias for TLS. Deprecated in Python 3.6, use TLS.
TLS           Negotiate highest possible version between client/server.
              Can yield SSL. (Python 3.6+)
TLSv1         TLS 1.0
TLSv1_1       TLS 1.1 (Python 3.4+)
TLSv1_2       TLS 1.2 (Python 3.4+)
TLS_SERVER    Auto-negotiate the highest protocol version like TLS,
              but only support server-side SSLSocket connections.
              (Python 3.6+)
============= ============

.. versionchanged:: 19.7
   The default value has been changed from ``ssl.PROTOCOL_TLSv1`` to
   ``ssl.PROTOCOL_SSLv23``.
.. versionchanged:: 20.0
   This setting now accepts string names based on ``ssl.PROTOCOL_``
   constants.

.. _cert-reqs:

``cert_reqs``
~~~~~~~~~~~~~

**Command line:** ``--cert-reqs``

**Default:** ``<VerifyMode.CERT_NONE: 0>``

Whether client certificate is required (see stdlib ssl module's)

.. _ca-certs:

``ca_certs``
~~~~~~~~~~~~

**Command line:** ``--ca-certs FILE``

**Default:** ``None``

CA certificates file

.. _suppress-ragged-eofs:

``suppress_ragged_eofs``
~~~~~~~~~~~~~~~~~~~~~~~~

**Command line:** ``--suppress-ragged-eofs``

**Default:** ``True``

Suppress ragged EOFs (see stdlib ssl module's)

.. _do-handshake-on-connect:

``do_handshake_on_connect``
~~~~~~~~~~~~~~~~~~~~~~~~~~~

**Command line:** ``--do-handshake-on-connect``

**Default:** ``False``

Whether to perform SSL handshake on socket connect (see stdlib ssl module's)

.. _ciphers:

``ciphers``
~~~~~~~~~~~

**Command line:** ``--ciphers``

**Default:** ``None``

SSL Cipher suite to use, in the format of an OpenSSL cipher list.

By default we use the default cipher list from Python's ``ssl`` module,
which contains ciphers considered strong at the time of each Python
release.

As a recommended alternative, the Open Web App Security Project (OWASP)
offers `a vetted set of strong cipher strings rated A+ to C-
<https://www.owasp.org/index.php/TLS_Cipher_String_Cheat_Sheet>`_.
OWASP provides details on user-agent compatibility at each security level.

See the `OpenSSL Cipher List Format Documentation
<https://www.openssl.org/docs/manmaster/man1/ciphers.html#CIPHER-LIST-FORMAT>`_
for details on the format of an OpenSSL cipher list.

Security
--------

.. _limit-request-line:

``limit_request_line``
~~~~~~~~~~~~~~~~~~~~~~

**Command line:** ``--limit-request-line INT``

**Default:** ``4094``

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

.. _limit-request-fields:

``limit_request_fields``
~~~~~~~~~~~~~~~~~~~~~~~~

**Command line:** ``--limit-request-fields INT``

**Default:** ``100``

Limit the number of HTTP headers fields in a request.

This parameter is used to limit the number of headers in a request to
prevent DDOS attack. Used with the *limit_request_field_size* it allows
more safety. By default this value is 100 and can't be larger than
32768.

.. _limit-request-field-size:

``limit_request_field_size``
~~~~~~~~~~~~~~~~~~~~~~~~~~~~

**Command line:** ``--limit-request-field_size INT``

**Default:** ``8190``

Limit the allowed size of an HTTP request header field.

Value is a positive number or 0. Setting it to 0 will allow unlimited
header field sizes.

.. warning::
   Setting this parameter to a very high or unlimited value can open
   up for DDOS attacks.

Server Hooks
------------

.. _on-starting:

``on_starting``
~~~~~~~~~~~~~~~

**Default:** 

.. code-block:: python

        def on_starting(server):
            pass

Called just before the master process is initialized.

The callable needs to accept a single instance variable for the Arbiter.

.. _on-reload:

``on_reload``
~~~~~~~~~~~~~

**Default:** 

.. code-block:: python

        def on_reload(server):
            pass

Called to recycle workers during a reload via SIGHUP.

The callable needs to accept a single instance variable for the Arbiter.

.. _when-ready:

``when_ready``
~~~~~~~~~~~~~~

**Default:** 

.. code-block:: python

        def when_ready(server):
            pass

Called just after the server is started.

The callable needs to accept a single instance variable for the Arbiter.

.. _pre-fork:

``pre_fork``
~~~~~~~~~~~~

**Default:** 

.. code-block:: python

        def pre_fork(server, worker):
            pass

Called just before a worker is forked.

The callable needs to accept two instance variables for the Arbiter and
new Worker.

.. _post-fork:

``post_fork``
~~~~~~~~~~~~~

**Default:** 

.. code-block:: python

        def post_fork(server, worker):
            pass

Called just after a worker has been forked.

The callable needs to accept two instance variables for the Arbiter and
new Worker.

.. _post-worker-init:

``post_worker_init``
~~~~~~~~~~~~~~~~~~~~

**Default:** 

.. code-block:: python

        def post_worker_init(worker):
            pass

Called just after a worker has initialized the application.

The callable needs to accept one instance variable for the initialized
Worker.

.. _worker-int:

``worker_int``
~~~~~~~~~~~~~~

**Default:** 

.. code-block:: python

        def worker_int(worker):
            pass

Called just after a worker exited on SIGINT or SIGQUIT.

The callable needs to accept one instance variable for the initialized
Worker.

.. _worker-abort:

``worker_abort``
~~~~~~~~~~~~~~~~

**Default:** 

.. code-block:: python

        def worker_abort(worker):
            pass

Called when a worker received the SIGABRT signal.

This call generally happens on timeout.

The callable needs to accept one instance variable for the initialized
Worker.

.. _pre-exec:

``pre_exec``
~~~~~~~~~~~~

**Default:** 

.. code-block:: python

        def pre_exec(server):
            pass

Called just before a new master process is forked.

The callable needs to accept a single instance variable for the Arbiter.

.. _pre-request:

``pre_request``
~~~~~~~~~~~~~~~

**Default:** 

.. code-block:: python

        def pre_request(worker, req):
            worker.log.debug("%s %s" % (req.method, req.path))

Called just before a worker processes the request.

The callable needs to accept two instance variables for the Worker and
the Request.

.. _post-request:

``post_request``
~~~~~~~~~~~~~~~~

**Default:** 

.. code-block:: python

        def post_request(worker, req, environ, resp):
            pass

Called after a worker processes the request.

The callable needs to accept two instance variables for the Worker and
the Request.

.. _child-exit:

``child_exit``
~~~~~~~~~~~~~~

**Default:** 

.. code-block:: python

        def child_exit(server, worker):
            pass

Called just after a worker has been exited, in the master process.

The callable needs to accept two instance variables for the Arbiter and
the just-exited Worker.

.. versionadded:: 19.7

.. _worker-exit:

``worker_exit``
~~~~~~~~~~~~~~~

**Default:** 

.. code-block:: python

        def worker_exit(server, worker):
            pass

Called just after a worker has been exited, in the worker process.

The callable needs to accept two instance variables for the Arbiter and
the just-exited Worker.

.. _nworkers-changed:

``nworkers_changed``
~~~~~~~~~~~~~~~~~~~~

**Default:** 

.. code-block:: python

        def nworkers_changed(server, new_value, old_value):
            pass

Called just after *num_workers* has been changed.

The callable needs to accept an instance variable of the Arbiter and
two integers of number of workers after and before change.

If the number of workers is set for the first time, *old_value* would
be ``None``.

.. _on-exit:

``on_exit``
~~~~~~~~~~~

**Default:** 

.. code-block:: python

        def on_exit(server):
            pass

Called just before exiting Gunicorn.

The callable needs to accept a single instance variable for the Arbiter.

Server Mechanics
----------------

.. _preload-app:

``preload_app``
~~~~~~~~~~~~~~~

**Command line:** ``--preload``

**Default:** ``False``

Load application code before the worker processes are forked.

By preloading an application you can save some RAM resources as well as
speed up server boot times. Although, if you defer application loading
to each worker process, you can reload your application code easily by
restarting workers.

.. _sendfile:

``sendfile``
~~~~~~~~~~~~

**Command line:** ``--no-sendfile``

**Default:** ``None``

Disables the use of ``sendfile()``.

If not set, the value of the ``SENDFILE`` environment variable is used
to enable or disable its usage.

.. versionadded:: 19.2
.. versionchanged:: 19.4
   Swapped ``--sendfile`` with ``--no-sendfile`` to actually allow
   disabling.
.. versionchanged:: 19.6
   added support for the ``SENDFILE`` environment variable

.. _reuse-port:

``reuse_port``
~~~~~~~~~~~~~~

**Command line:** ``--reuse-port``

**Default:** ``False``

Set the ``SO_REUSEPORT`` flag on the listening socket.

.. versionadded:: 19.8

.. _chdir:

``chdir``
~~~~~~~~~

**Command line:** ``--chdir``

**Default:** ``'.'``

Change directory to specified directory before loading apps. 

Default is the current directory.

.. _daemon:

``daemon``
~~~~~~~~~~

**Command line:** ``-D`` or ``--daemon``

**Default:** ``False``

Daemonize the Gunicorn process.

Detaches the server from the controlling terminal and enters the
background.

.. _raw-env:

``raw_env``
~~~~~~~~~~~

**Command line:** ``-e ENV`` or ``--env ENV``

**Default:** ``[]``

Set environment variables in the execution environment.

Should be a list of strings in the ``key=value`` format.

For example on the command line:

.. code-block:: console

    $ gunicorn -b 127.0.0.1:8000 --env FOO=1 test:app

Or in the configuration file:

.. code-block:: python

    raw_env = ["FOO=1"]

.. _pidfile:

``pidfile``
~~~~~~~~~~~

**Command line:** ``-p FILE`` or ``--pid FILE``

**Default:** ``None``

A filename to use for the PID file.

If not set, no PID file will be written.

.. _worker-tmp-dir:

``worker_tmp_dir``
~~~~~~~~~~~~~~~~~~

**Command line:** ``--worker-tmp-dir DIR``

**Default:** ``None``

A directory to use for the worker heartbeat temporary file.

If not set, the default temporary directory will be used.

.. note::
   The current heartbeat system involves calling ``os.fchmod`` on
   temporary file handlers and may block a worker for arbitrary time
   if the directory is on a disk-backed filesystem.

   See :ref:`blocking-os-fchmod` for more detailed information
   and a solution for avoiding this problem.

.. _user:

``user``
~~~~~~~~

**Command line:** ``-u USER`` or ``--user USER``

**Default:** ``501``

Switch worker processes to run as this user.

A valid user id (as an integer) or the name of a user that can be
retrieved with a call to ``pwd.getpwnam(value)`` or ``None`` to not
change the worker process user.

.. _group:

``group``
~~~~~~~~~

**Command line:** ``-g GROUP`` or ``--group GROUP``

**Default:** ``20``

Switch worker process to run as this group.

A valid group id (as an integer) or the name of a user that can be
retrieved with a call to ``pwd.getgrnam(value)`` or ``None`` to not
change the worker processes group.

.. _umask:

``umask``
~~~~~~~~~

**Command line:** ``-m INT`` or ``--umask INT``

**Default:** ``0``

A bit mask for the file mode on files written by Gunicorn.

Note that this affects unix socket permissions.

A valid value for the ``os.umask(mode)`` call or a string compatible
with ``int(value, 0)`` (``0`` means Python guesses the base, so values
like ``0``, ``0xFF``, ``0022`` are valid for decimal, hex, and octal
representations)

.. _initgroups:

``initgroups``
~~~~~~~~~~~~~~

**Command line:** ``--initgroups``

**Default:** ``False``

If true, set the worker process's group access list with all of the
groups of which the specified username is a member, plus the specified
group id.

.. versionadded:: 19.7

.. _tmp-upload-dir:

``tmp_upload_dir``
~~~~~~~~~~~~~~~~~~

**Default:** ``None``

Directory to store temporary request data as they are read.

This may disappear in the near future.

This path should be writable by the process permissions set for Gunicorn
workers. If not specified, Gunicorn will choose a system generated
temporary directory.

.. _secure-scheme-headers:

``secure_scheme_headers``
~~~~~~~~~~~~~~~~~~~~~~~~~

**Default:** ``{'X-FORWARDED-PROTOCOL': 'ssl', 'X-FORWARDED-PROTO': 'https', 'X-FORWARDED-SSL': 'on'}``

A dictionary containing headers and values that the front-end proxy
uses to indicate HTTPS requests. These tell Gunicorn to set
``wsgi.url_scheme`` to ``https``, so your application can tell that the
request is secure.

The dictionary should map upper-case header names to exact string
values. The value comparisons are case-sensitive, unlike the header
names, so make sure they're exactly what your front-end proxy sends
when handling HTTPS requests.

It is important that your front-end proxy configuration ensures that
the headers defined here can not be passed directly from the client.

.. _forwarded-allow-ips:

``forwarded_allow_ips``
~~~~~~~~~~~~~~~~~~~~~~~

**Command line:** ``--forwarded-allow-ips STRING``

**Default:** ``'127.0.0.1'``

Front-end's IPs from which allowed to handle set secure headers.
(comma separate).

Set to ``*`` to disable checking of Front-end IPs (useful for setups
where you don't know in advance the IP address of Front-end, but
you still trust the environment).

By default, the value of the ``FORWARDED_ALLOW_IPS`` environment
variable. If it is not defined, the default is ``"127.0.0.1"``.

.. _pythonpath:

``pythonpath``
~~~~~~~~~~~~~~

**Command line:** ``--pythonpath STRING``

**Default:** ``None``

A comma-separated list of directories to add to the Python path.

e.g.
``'/home/djangoprojects/myproject,/home/python/mylibrary'``.

.. _paste:

``paste``
~~~~~~~~~

**Command line:** ``--paste STRING`` or ``--paster STRING``

**Default:** ``None``

Load a PasteDeploy config file. The argument may contain a ``#``
symbol followed by the name of an app section from the config file,
e.g. ``production.ini#admin``.

At this time, using alternate server blocks is not supported. Use the
command line arguments to control server configuration instead.

.. _proxy-protocol:

``proxy_protocol``
~~~~~~~~~~~~~~~~~~

**Command line:** ``--proxy-protocol``

**Default:** ``False``

Enable detect PROXY protocol (PROXY mode).

Allow using HTTP and Proxy together. It may be useful for work with
stunnel as HTTPS frontend and Gunicorn as HTTP server.

PROXY protocol: http://haproxy.1wt.eu/download/1.5/doc/proxy-protocol.txt

Example for stunnel config::

    [https]
    protocol = proxy
    accept  = 443
    connect = 80
    cert = /etc/ssl/certs/stunnel.pem
    key = /etc/ssl/certs/stunnel.key

.. _proxy-allow-ips:

``proxy_allow_ips``
~~~~~~~~~~~~~~~~~~~

**Command line:** ``--proxy-allow-from``

**Default:** ``'127.0.0.1'``

Front-end's IPs from which allowed accept proxy requests (comma separate).

Set to ``*`` to disable checking of Front-end IPs (useful for setups
where you don't know in advance the IP address of Front-end, but
you still trust the environment)

.. _raw-paste-global-conf:

``raw_paste_global_conf``
~~~~~~~~~~~~~~~~~~~~~~~~~

**Command line:** ``--paste-global CONF``

**Default:** ``[]``

Set a PasteDeploy global config variable in ``key=value`` form.

The option can be specified multiple times.

The variables are passed to the the PasteDeploy entrypoint. Example::

    $ gunicorn -b 127.0.0.1:8000 --paste development.ini --paste-global FOO=1 --paste-global BAR=2

.. versionadded:: 19.7

.. _strip-header-spaces:

``strip_header_spaces``
~~~~~~~~~~~~~~~~~~~~~~~

**Command line:** ``--strip-header-spaces``

**Default:** ``False``

Strip spaces present between the header name and the the ``:``.

This is known to induce vulnerabilities and is not compliant with the HTTP/1.1 standard.
See https://portswigger.net/research/http-desync-attacks-request-smuggling-reborn.

Use with care and only if necessary.

Server Socket
-------------

.. _bind:

``bind``
~~~~~~~~

**Command line:** ``-b ADDRESS`` or ``--bind ADDRESS``

**Default:** ``['127.0.0.1:8000']``

The socket to bind.

A string of the form: ``HOST``, ``HOST:PORT``, ``unix:PATH``,
``fd://FD``. An IP is a valid ``HOST``.

.. versionchanged:: 20.0
   Support for ``fd://FD`` got added.

Multiple addresses can be bound. ex.::

    $ gunicorn -b 127.0.0.1:8000 -b [::1]:8000 test:app

will bind the `test:app` application on localhost both on ipv6
and ipv4 interfaces.

If the ``PORT`` environment variable is defined, the default
is ``['0.0.0.0:$PORT']``. If it is not defined, the default
is ``['127.0.0.1:8000']``.

.. _backlog:

``backlog``
~~~~~~~~~~~

**Command line:** ``--backlog INT``

**Default:** ``2048``

The maximum number of pending connections.

This refers to the number of clients that can be waiting to be served.
Exceeding this number results in the client getting an error when
attempting to connect. It should only affect servers under significant
load.

Must be a positive integer. Generally set in the 64-2048 range.

Worker Processes
----------------

.. _workers:

``workers``
~~~~~~~~~~~

**Command line:** ``-w INT`` or ``--workers INT``

**Default:** ``1``

The number of worker processes for handling requests.

A positive integer generally in the ``2-4 x $(NUM_CORES)`` range.
You'll want to vary this a bit to find the best for your particular
application's work load.

By default, the value of the ``WEB_CONCURRENCY`` environment variable.
If it is not defined, the default is ``1``.

.. _worker-class:

``worker_class``
~~~~~~~~~~~~~~~~

**Command line:** ``-k STRING`` or ``--worker-class STRING``

**Default:** ``'sync'``

The type of workers to use.

The default class (``sync``) should handle most "normal" types of
workloads. You'll want to read :doc:`design` for information on when
you might want to choose one of the other worker classes. Required
libraries may be installed using setuptools' ``extras_require`` feature.

A string referring to one of the following bundled classes:

* ``sync``
* ``eventlet`` - Requires eventlet >= 0.24.1 (or install it via
  ``pip install gunicorn[eventlet]``)
* ``gevent``   - Requires gevent >= 1.4 (or install it via
  ``pip install gunicorn[gevent]``)
* ``tornado``  - Requires tornado >= 0.2 (or install it via
  ``pip install gunicorn[tornado]``)
* ``gthread``  - Python 2 requires the futures package to be installed
  (or install it via ``pip install gunicorn[gthread]``)

Optionally, you can provide your own worker by giving Gunicorn a
Python path to a subclass of ``gunicorn.workers.base.Worker``.
This alternative syntax will load the gevent class:
``gunicorn.workers.ggevent.GeventWorker``.

.. _threads:

``threads``
~~~~~~~~~~~

**Command line:** ``--threads INT``

**Default:** ``1``

The number of worker threads for handling requests.

Run each worker with the specified number of threads.

A positive integer generally in the ``2-4 x $(NUM_CORES)`` range.
You'll want to vary this a bit to find the best for your particular
application's work load.

If it is not defined, the default is ``1``.

This setting only affects the Gthread worker type.

.. note::
   If you try to use the ``sync`` worker type and set the ``threads``
   setting to more than 1, the ``gthread`` worker type will be used
   instead.

.. _worker-connections:

``worker_connections``
~~~~~~~~~~~~~~~~~~~~~~

**Command line:** ``--worker-connections INT``

**Default:** ``1000``

The maximum number of simultaneous clients.

This setting only affects the ``gthread``, ``eventlet`` and ``gevent`` worker types.

.. _max-requests:

``max_requests``
~~~~~~~~~~~~~~~~

**Command line:** ``--max-requests INT``

**Default:** ``0``

The maximum number of requests a worker will process before restarting.

Any value greater than zero will limit the number of requests a worker
will process before automatically restarting. This is a simple method
to help limit the damage of memory leaks.

If this is set to zero (the default) then the automatic worker
restarts are disabled.

.. _max-requests-jitter:

``max_requests_jitter``
~~~~~~~~~~~~~~~~~~~~~~~

**Command line:** ``--max-requests-jitter INT``

**Default:** ``0``

The maximum jitter to add to the *max_requests* setting.

The jitter causes the restart per worker to be randomized by
``randint(0, max_requests_jitter)``. This is intended to stagger worker
restarts to avoid all workers restarting at the same time.

.. versionadded:: 19.2

.. _timeout:

``timeout``
~~~~~~~~~~~

**Command line:** ``-t INT`` or ``--timeout INT``

**Default:** ``30``

Workers silent for more than this many seconds are killed and restarted.

Value is a positive number or 0. Setting it to 0 has the effect of
infinite timeouts by disabling timeouts for all workers entirely.

Generally, the default of thirty seconds should suffice. Only set this
noticeably higher if you're sure of the repercussions for sync workers.
For the non sync workers it just means that the worker process is still
communicating and is not tied to the length of time required to handle a
single request.

.. _graceful-timeout:

``graceful_timeout``
~~~~~~~~~~~~~~~~~~~~

**Command line:** ``--graceful-timeout INT``

**Default:** ``30``

Timeout for graceful workers restart.

After receiving a restart signal, workers have this much time to finish
serving requests. Workers still alive after the timeout (starting from
the receipt of the restart signal) are force killed.

.. _keepalive:

``keepalive``
~~~~~~~~~~~~~

**Command line:** ``--keep-alive INT``

**Default:** ``2``

The number of seconds to wait for requests on a Keep-Alive connection.

Generally set in the 1-5 seconds range for servers with direct connection
to the client (e.g. when you don't have separate load balancer). When
Gunicorn is deployed behind a load balancer, it often makes sense to
set this to a higher value.

.. note::
   ``sync`` worker does not support persistent connections and will
   ignore this option.

