.. _custom:

==================
Custom Application
==================

.. versionadded:: 19.0

Sometimes, you want to integrate Gunicorn with your WSGI application. In this
case, you can inherit from :class:`gunicorn.app.base.BaseApplication`.

Here is a small example where we create a very small WSGI app and load it with
a custom Application:

.. literalinclude:: ../../examples/standalone_app.py
    :lines: 11-60

Direct Usage of Existing WSGI Apps
----------------------------------

If necessary, you can run Gunicorn straight from python, allowing you to 
specify a WSGI-compatible application at runtime. This might be useful for 
rolling deploys or in the case of using PEX files to deploy your application,
as the app and Gunicorn can be bundled in the same PEX file. At the time of
writing, you can import and instantiate a WSGIApplication like so:

.. code-block:: python
    from gunicorn.app.wsgiapp import WSGIApplication
    WSGIApplication("%(prog)s [OPTIONS] [APP_MODULE]").run()

This can be used to run WSGI-compatible app instances such as those produced
by Flask or Django. Assuming that the code above is in a file called `run.py`,
your application's WSGI instance is called `app`, and it's exported by a package
called `exampleapi`, then you should be able to fire up your server with a
command similar to '``python run.py exampleapi:app``'. 

This command will work with any Gunicorn CLI parameters or a config file - just
pass them along as if you're directly giving them to Gunicorn as below

.. code-block:: python
    # Custom parameters
    python run.py exampleapi:app --bind=0.0.0.0:8081 --workers=4
    # Using a config file
    python run.py exampleapi:app -c config.py
