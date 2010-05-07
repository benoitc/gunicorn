template: doc.html
title: FAQ

FAQ
===

How do I know which type of worker to use?
  Test. Read the "Synchronous vs Asynchronous workers" section on the 
  deployment_ page. Test some more.

What types of workers are there?
  These can all be used with the ``-k`` option and specifying them
  as ``egg:gunicorn#$(NAME)`` where ``$(NAME)`` is chosen from this list.
  
  * ``sync`` - The default synchronous worker
  * ``eventlet`` - Asynchronous workers based on Greenlets
  * ``gevent`` - Asynchronous workers based on Greenlets
  * ``tornado`` - Asynchronous workers based on FriendFeed's Tornado server.

How might I test a proxy configuration?
  Check out slowloris_ for a script that will generate significant slow
  traffic. If your application remains responsive through out that test you
  should be comfortable that all is well with your configuration.

How do I reload my application in Gunicorn?
  You can gracefully reload by sending HUP signal to gunicorn::

    $ kill -HUP masterpid

How do I increase or decrease the number of running workers dynamically?
    To increase the worker count by one::

        $ kill -TTIN $masterpid
    
    To decrease the worker count by one::

        $ kill -TTOU $masterpid

How can I figure out the best number of worker processes?
  Start gunicorn with an approximate number of worker processes. Then use the
  TTIN and/or TTOU signals to adjust the number of workers under load.

How do I set SCRIPT_NAME?
    By default ``SCRIPT_NAME`` is an empy string. The value could be set by
    setting ``SCRIPT_NAME`` in the environment or as an HTTP header.

How can I name processes?
    You need to install the Python package setproctitle_. Then you can specify
    a base process name on the command line (``-n``) or in the configuration
    file.

.. _deployment: http://gunicorn.org/deployment.html
.. _slowloris: http://ha.ckers.org/slowloris/
.. _setproctitle: http://pypi.python.org/pypi/setproctitle
.. _Eventlet: http://eventlet.net
.. _Gevent: http://gevent.org