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
    :start-after: # See the NOTICE for more information
    :lines: 2-

Using server hooks
------------------

If you wish to include server hooks in your custom application, you can specify a function in the config options.  Here is an example with the `pre_fork` hook:

.. code-block:: python

   def pre_fork(server, worker):
       print(f"pre-fork server {server} worker {worker}", file=sys.stderr)

   # ...
   if __name__ == '__main__':
       options = {
           'bind': '%s:%s' % ('127.0.0.1', '8080'),
           'workers': number_of_workers(),
           'pre_fork': pre_fork,
       }


Direct Usage of Existing WSGI Apps
----------------------------------

If necessary, you can run Gunicorn straight from Python, allowing you to
specify a WSGI-compatible application at runtime. This can be handy for
rolling deploys or in the case of using PEX files to deploy your application,
as the app and Gunicorn can be bundled in the same PEX file. Gunicorn has
this functionality built-in as a first class citizen known as
:class:`gunicorn.app.wsgiapp`. This can be used to run WSGI-compatible app
instances such as those produced by Flask or Django. Assuming your WSGI API
package is *exampleapi*, and your application instance is *app*, this is all
you need to get going::

    gunicorn.app.wsgiapp exampleapi:app

This command will work with any Gunicorn CLI parameters or a config file - just
pass them along as if you're directly giving them to Gunicorn:

.. code-block:: bash

   # Custom parameters
   $ python gunicorn.app.wsgiapp exampleapi:app --bind=0.0.0.0:8081 --workers=4
   # Using a config file
   $ python gunicorn.app.wsgiapp exampleapi:app -c config.py
    
Note for those using PEX: use ``-c gunicorn`` as your entry at build
time, and your compiled app should work with the entry point passed to it at
run time. 

.. code-block:: bash

   # Generic pex build command via bash from root of exampleapi project
   $ pex . -v -c gunicorn -o compiledapp.pex
   # Running it
   ./compiledapp.pex exampleapi:app -c gunicorn_config.py
