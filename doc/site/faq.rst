template: doc.html
title: FAQ

FAQ
===

How do I reload my application in Gunicorn?
  You can gracefully reload by sending HUP signal to gunicorn::

    $ kill -HUP masterpid


How do I increase or decrease the number of running workers dynamically?
    To increase the worker count by one::

        $ kill -TTIN $masterpid
    
    To decrease the worker count by one::

        $ kill -TTOUT $masterpid

  
How do I set SCRIPT_NAME?
    By default ``SCRIPT_NAME`` is an empy string. The value could be set by
    setting ``SCRIPT_NAME`` in the environment or as an HTTP header.

How to name processes?
    You need to install the Python package `setproctitle <http://pypi.python.org/pypi/setproctitle>`_. Then you can name your process with `-n` or just let the default.