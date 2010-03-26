template: doc.html
title: Command Line Usage

Command Line Usage
==================

- `WSGI applications`_
- `Django projects`_
- `Paste-compatible projects`_

WSGI applications
-----------------

To launch the `example application`_ packaged with Gunicorn::

    $ cd /path/to/gunicorn/examples/
    $ gunicorn --workers=2 test:app

The module ``test:app`` specifies the complete module name and WSGI callable.
You can replace it with anything that is available on your ``PYTHONPATH`` like
such::

    $ cd ~/
    $ gunicorn --workers=12 awesomeproject.wsgi.main:main_app
    
To launch the `websocket example`_ application using `Eventlet`_::

        $ cd /path/to/gunicorn/examples/
        $ gunicorn -w 12 -a "egg:gunicorn#eventlet" websocket:app

You should then be able to visit ``http://localhost:8000`` to see output.

Full command line usage
+++++++++++++++++++++++

::

  $ gunicorn --help
  Usage: gunicorn [OPTIONS] [APP_MODULE]
  
  Options:
    -c CONFIG, --config=CONFIG
                          Config file. [none]
    -b BIND, --bind=BIND  Adress to listen on. Ex. 127.0.0.1:8000 or
                          unix:/tmp/gunicorn.sock
    -w WORKERS, --workers=WORKERS
                          Number of workers to spawn. [1]
    -a ARBITER, --arbiter=ARBITER
                          gunicorn arbiter entry point or module
                          [egg:gunicorn#main]
    -p PIDFILE, --pid=PIDFILE
                          set the background PID FILE
    -D, --daemon          Run daemonized in the background.
    -m UMASK, --umask=UMASK
                          Define umask of daemon process
    -u USER, --user=USER  Change worker user
    -g GROUP, --group=GROUP
                          Change worker group
    -n APP_NAME, --name=APP_NAME
                          Application name
    --log-level=LOGLEVEL  Log level below which to silence messages. [info]
    --log-file=LOGFILE    Log to a file. - equals stdout. [-]
    -d, --debug           Debug mode. only 1 worker.
    --version             show program's version number and exit
    -h, --help            show this help message and exit

Django Projects
---------------

`Django`_ projects can be handled easily by Gunicorn using the
``gunicorn_django`` command::

    $ cd $yourdjangoproject
    $ gunicorn_django --workers=2

But you can also use the ``run_gunicorn`` `admin command`_ like the other
``management.py`` commands.

Add ``"gunicorn"`` to INSTALLED_APPS in your settings file::

    INSTALLED_APPS = (
        ...
        "gunicorn",
    )
  
Then run::

    python manage.py run_gunicorn
  

Paste-compatible projects
-------------------------

For `Paste`_ compatible projects (`Pylons`_, `TurboGears 2`_, ...) use the
``gunicorn_paste`` command::

    $ cd $yourpasteproject
    $ gunicorn_paste --workers=2 development.ini

To use the ``paster`` command add a sever section for Gunicorn::

    [server:main]
    use = egg:gunicorn#main
    host = 127.0.0.1
    port = 5000

And then all you need to do is::

    $ cd $yourpasteproject
    $ paster serve development.ini workers=2
 
.. _`example application`: http://github.com/benoitc/gunicorn/blob/master/examples/test.py
.. _`websocket example`: http://github.com/benoitc/gunicorn/blob/master/examples/websocket.py
.. _Django: http://djangoproject.com
.. _`admin command`: http://docs.djangoproject.com/en/dev/howto/custom-management-commands/
.. _Paste: http://pythonpaste.org/script/
.. _Pylons: http://pylonshq.com/
.. _Turbogears 2: http://turbogears.org/2.0/
.. _Eventlet: http://eventlet.net