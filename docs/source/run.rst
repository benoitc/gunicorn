================
Running Gunicorn
================

You can run Gunicorn by using commands or integrate with Django or Paster. For
deploying Gunicorn in production see :doc:`deploy`.

Commands
========

After installing Gunicorn you will have access to the command line script
``gunicorn``.

gunicorn
--------

Basic usage::

    $ gunicorn [OPTIONS] APP_MODULE

Where ``APP_MODULE`` is of the pattern ``$(MODULE_NAME):$(VARIABLE_NAME)``. The
module name can be a full dotted path. The variable name refers to a WSGI
callable that should be found in the specified module.

Example with test app::

    $ cd examples
    $ cat test.py
    # -*- coding: utf-8 -
    #
    # This file is part of gunicorn released under the MIT license.
    # See the NOTICE for more information.

    def app(environ, start_response):
        """Simplest possible application object"""
        data = 'Hello, World!\n'
        status = '200 OK'
        response_headers = [
            ('Content-type','text/plain'),
            ('Content-Length', str(len(data)))
        ]
        start_response(status, response_headers)
        return iter([data])

    $ gunicorn --workers=2 test:app


Integration
===========

We also provide integration for both Django and Paster applications.

Django
------

gunicorn just needs to be called with a the location of a WSGI
application object.:

    gunicorn [OPTIONS] APP_MODULE

Where APP_MODULE is of the pattern MODULE_NAME:VARIABLE_NAME. The module
name should be a full dotted path. The variable name refers to a WSGI
callable that should be found in the specified module.

So for a typical Django project, invoking gunicorn would look like:

    gunicorn --env DJANGO_SETTINGS_MODULE=myproject.settings myproject.wsgi:application

(This requires that your project be on the Python path; the simplest way
to ensure that is to run this command from the same directory as your
manage.py file.)

You can use the
`--env <http://docs.gunicorn.org/en/latest/settings.html#raw-env>`_ option
to set the path to load the settings. In case you need it you can also
add your application path to PYTHONPATH using the
`--pythonpath <http://docs.gunicorn.org/en/latest/settings.html#pythonpath>`_ option.

Paste
-----

If you are a user/developer of a paste-compatible framework/app (as
Pyramid, Pylons and Turbogears) you can use the gunicorn
`--paste <http://docs.gunicorn.org/en/latest/settings.html#paste>`_ option
to run your application.

For example:

    gunicorn --paste development.ini -b :8080 --chdir /path/to/project

Or use a different application:

    gunicorn --paste development.ini#admin -b :8080 --chdir /path/to/project

It is all here. No configuration files nor additional python modules to
write !!
