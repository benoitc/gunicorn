template: doc.html
title: Deployment

Production Setup
================

There are two general classes of configuration for Gunicorn. For the time
being these will are referred to as "fast clients" and "sleepy applications".

Fast Clients
------------

Generally speaking when we say "fast clients" what we really mean is that the
time taken to process a client from the time a socket is accepted until
the time the socket is closed is well defined to be short. This means that
clients are buffered by an upstream proxy (otherwise clients can send or
receive data slowly) and that your application code does not have major
blocking sections (a web request to the internet might occasionally take a
non trivial amount of time).

Traditional webapps are generally fine for fast client configurations.
Deployments should generally default to this type of configuration unless it is
known that the application code wants to do long-polling, comet, web sockets or
has other potentially long operations (on the order of seconds).

Sleepy Applications
-------------------

Any application that requires an undefined amount of time for client processing
is considered a sleepy application. If you are wanting a platform that is
capable of handling comet connections, long polling, or potentially long
blocking operations (requests to external web services, ie Facebook Connect)
then you'll want to use an async arbiter.

Nginx Config for fast clients handling
--------------------------------------

Although there are many HTTP proxies available, we strongly advise that you
use Nginx_. If you choose another proxy server you need to make sure that it
buffers slow clients when you use default Gunicorn arbiter. Without this
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

To handle sleepy applications, just add the line `proxy_buffering off;` under
the proxy_redirect directive::

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
  ....

Daemon Monitoring
-----------------

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
