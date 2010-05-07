template: doc.html
title: Deployment

Production Setup
================

Synchronous vs Asynchronous workers
-----------------------------------

The default configuration of Gunicorn assumes that your application code is
mostly CPU bound. The default worker class is a simple single threaded loop that
just processes requests as they are received. In general, most applications will
do just fine with this sort of configuration.

This CPU bound assumption is why the default configuration needs to use a
buffering HTTP proxy like Nginx_ to protect the Gunicorn server. If we allowed
direct connections a client could send a request slowly thus starving the server
of free worker processes (because they're all stuck waiting for data).

Example use-cases for asynchronous workers:

  * Applications making long blocking calls (Ie, to external web services)
  * Serving requests directly to the internet
  * Streaming requests and responses
  * Long polling
  * Web sockets
  * Comet

Basic Nginx Configuration
-------------------------

Although there are many HTTP proxies available, we strongly advise that you
use Nginx_. If you choose another proxy server you need to make sure that it
buffers slow clients when you use default Gunicorn workers. Without this
buffering Gunicorn will be easily susceptible to Denial-Of-Service attacks.
You can use slowloris_ to check if your proxy is behaving properly.

An `example configuration`_ file for fast clients with Nginx_::

    worker_processes 1;
 
    user nobody nogroup;
    pid /tmp/nginx.pid;
    error_log /tmp/nginx.error.log;
 
    events {
        worker_connections 1024;
        accept_mutex off;
    }
 
    http {
        include mime.types;
        default_type application/octet-stream;
        access_log /tmp/nginx.access.log combined;
        sendfile on;

        upstream app_server {
            server unix:/tmp/gunicorn.sock fail_timeout=0;
            # For a TCP configuration:
            # server 192.168.0.7:8000 fail_timeout=0;
        }
 
        server {
            listen 80 default;
            client_max_body_size 4G;
            server_name _;
 
            keepalive_timeout 5;
 
            # path for static files
            root /path/to/app/current/public;
 
            location / {
                proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
                proxy_set_header Host $http_host;
                proxy_redirect off;
 
                if (!-f $request_filename) {
                    proxy_pass http://app_server;
                    break;
                }
            }
 
            error_page 500 502 503 504 /500.html;
            location = /500.html {
                root /path/to/app/current/public;
            }
        }
    }

If you want to be able to handle streaming request/responses or other fancy
features like Comet, Long polling, or Web sockets, you need to turn off the
proxy buffering. **When you do this** you must run with one of the async worker
classes.

To turn off buffering, you only need to add ``proxy_buffering off;`` to your
``location`` block::

  ...
  location / {
      proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
      proxy_set_header Host $http_host;
      proxy_redirect off;
      proxy_buffering off;

      if (!-f $request_filename) {
          proxy_pass http://app_server;
          break;
      }
  }
  ...

Working with Virtualenv
-----------------------

To serve an app from a Virtualenv_ it is generally easiest to just install
Gunicorn directly into the Virtualenv. This will create a set of Gunicorn
scripts for that Virtualenv which can be used to run applications normally.

If you have Virtualenv installed, you should be able to do something like
this::

    $ mkdir ~/venvs/
    $ virtualenv ~/venvs/webapp
    $ source ~/venvs/webapp/bin/activate
    $ ~/venvs/webapp/bin/easy_install -U gunicorn
    $ deactivate

Then you just need to use one of the three Gunicorn scripts that was installed
into ``~/venvs/webapp/bin``.

Daemon Monitoring
-----------------

.. note::
    Make sure that when using either of these service monitors you do not
    enable the Gunicorn's daemon mode. These monitors expect that the process
    they launch will be the process they need to monior. Daemonizing
    will fork-exec which creates an unmonitored process and generally just
    confuses the monitor services.


A popular method for deploying Gunicorn is to have it monitored by runit_.
An `example service`_ definition::

    #!/bin sh
    
    GUNICORN=/usr/local/bin/gunicorn
    ROOT=/path/to/project
    PID=/var/run/gunicorn.pid
    
    APP=main:application
 
    if [ -f $PID ]; then rm $PID fi
 
    cd $ROOT
    exec $GUNICORN -C $ROOT/gunicorn.conf.py --pidfile=$PID $APP

Another useful tool to monitor and control Gunicorn is Supervisor_. A 
`simple configuration`_ is::

    [program:gunicorn]
    command=/usr/local/bin/gunicorn main:application -c /path/to/project/gunicorn.conf.py
    directory=/path/to/project
    user=nobody
    autostart=true
    autorestart=true
    redirect_stderr=True


.. _Nginx: http://www.nginx.org
.. _slowloris: http://ha.ckers.org/slowloris/
.. _`example configuration`: http://github.com/benoitc/gunicorn/blob/master/examples/nginx.conf
.. _runit: http://smarden.org/runit/
.. _`example service`: http://github.com/benoitc/gunicorn/blob/master/examples/gunicorn_rc
.. _Supervisor: http://supervisord.org
.. _`simple configuration`: http://github.com/benoitc/gunicorn/blob/master/examples/supervisor.conf
.. _Virtualenv: http://pypi.python.org/pypi/virtualenv
