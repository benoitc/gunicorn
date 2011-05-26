template: doc.html
title: Deploy

_TOC_TOP_

.. contents::
    :backlinks: top

_TOC_BOT_

Nginx Configuration
-------------------

Although there are many HTTP proxies available, we strongly advise that you
use Nginx_. If you choose another proxy server you need to make sure that it
buffers slow clients when you use default Gunicorn workers. Without this
buffering Gunicorn will be easily susceptible to denial-of-service attacks.
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
                # checks for static file, if not found proxy to app
                try_files $uri @proxy_to_app;
            }

            location @proxy_to_app {
                proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
                proxy_set_header Host $http_host;
                proxy_redirect off;
 
                proxy_pass   http://app_server;
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

Using Virtualenv
----------------

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

Monitoring
----------

.. note::
    Make sure that when using either of these service monitors you do not
    enable the Gunicorn's daemon mode. These monitors expect that the process
    they launch will be the process they need to monior. Daemonizing
    will fork-exec which creates an unmonitored process and generally just
    confuses the monitor services.


Runit
+++++

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
If runit is installed, gunicorn should start running automatically as soon 
as you create the symlink.

If it doesn't start automatically, run the script directly to troubleshoot.


Supervisor
++++++++++

Another useful tool to monitor and control Gunicorn is Supervisor_. A 
`simple configuration`_ is::

    [program:gunicorn]
    command=/path/to/gunicorn main:application -c /path/to/gunicorn.conf.py
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
