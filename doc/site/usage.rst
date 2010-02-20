template: doc.html
title: Command line usage

Command line usage
==================

`Gunicorn`_ can easily be launched from the command line. This manual will show you how to use it with:

- `WSGI applications`_
- `Django projects`_
- `Paste-compatible projects`_

WSGI applications
-----------------

Here is how to launch your application in less than 30 seconds. Here is an example with our `test application <http://github.com/benoitc/gunicorn/blob/master/examples/test.py>`_::

  $ cd examples
  $ gunicorn --workers=2 test:application
  
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
    -p PIDFILE, --pid=PIDFILE
                          set the background PID FILE
    -D, --daemon          Run daemonized in the background.
    -m UMASK, --umask=UMASK
                          Define umask of daemon process
    -u USER, --user=USER  Change worker user
    -g GROUP, --group=GROUP
                          Change worker group
    --log-level=LOGLEVEL  Log level below which to silence messages. [info]
    --log-file=LOGFILE    Log to a file. - equals stdout. [-]
    -d, --debug           Debug mode. only 1 worker.
    --version             show program's version number and exit
    -h, --help            show this help message and exit

Django projects
---------------

`Django`_ projects can be handled easily by `Gunicorn`_ using the `gunicorn_django` command::

    $ cd yourdjangoproject
    $ gunicorn_django --workers=2


But you can also use `run_gunicorn` `admin command <http://docs.djangoproject.com/en/dev/howto/custom-management-commands/>`_ like all other commands.

add `gunicorn` to INSTALLED_APPS in the settings file::

  INSTALLED_APPS = (
    ...
    "gunicorn",
  )
  
Then run::

  python manage.py run_gunicorn
  

Paste-compatible projects
-------------------------

For `Paste`_ compatible projects (like `Pylons`_, `TurboGears 2`_, ...) use the `gunicorn_paste` command::

  $ cd your pasteproject
  $ gunicorn_paste --workers=2 development.ini

or usual **paster** command::

  $ cd your pasteproject
  $ paster serve development.ini workers=2
  
In this case don't forget to add a server section for `Gunicorn`_. Here is an example that use gunicorn as main server::

  [server:main]
  use = egg:gunicorn#main
  host = 127.0.0.1
  port = 5000
  
  
.. _Gunicorn: http://gunicorn.org
.. _Django: http://djangoproject.com
.. _Paste: http://pythonpaste.org/script/
.. _Pylons: http://pylonshq.com/
.. _Turbogears 2: http://turbogears.org/2.0/