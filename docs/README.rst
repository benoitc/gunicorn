Generate Documentation
======================

Requirements
------------

Install the documentation dependencies with::

    pip install -r requirements_dev.txt

This provides MkDocs with the Material theme and supporting plugins.


Build static HTML
-----------------
::

    mkdocs build

The rendered site is emitted into the ``site/`` directory.


Preview locally
---------------
::

    mkdocs serve

This serves the documentation at http://127.0.0.1:8000/ with live reload.
