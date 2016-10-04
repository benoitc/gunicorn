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
