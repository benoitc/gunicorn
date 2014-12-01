.. _configuration:

======================
Configuration Overview
======================

Gunicorn pulls configuration information from three distinct places.

The first place that Gunicorn will read configuration from is the framework
specific configuration file. Currently this only affects Paster applications.

The second source of configuration information is a configuration file that is
optionally specified on the command line. Anything specified in the Gunicorn
config file will override any framework specific settings.

Lastly, the command line arguments used to invoke Gunicorn are the final place
considered for configuration settings. If an option is specified on the command
line, this is the value that will be used.

Once again, in order of least to most authoritative:
    1. Framework Settings
    2. Configuration File
    3. Command Line


.. note::

    To check your configuration when using the command line or the
    configuration file you can run the following command::

        $ gunicorn --check-config APP_MODULE

    It also allows you to know if your application can be launched.


Command Line
============

If an option is specified on the command line, it overrides all other values
that may have been specified in the app specific settings, or in the optional
configuration file. Not all Gunicorn settings are available to be set from the
command line. To see the full list of command line settings you can do the
usual::

    $ gunicorn -h

There is also a ``--version`` flag available to the command line scripts that
isn't mentioned in the list of :ref:`settings <settings>`.


Configuration File
==================

The configuration file should be a valid Python source file. It only needs to
be readable from the file system. More specifically, it does not need to be
importable. Any Python is valid. Just consider that this will be run every time
you start Gunicorn (including when you signal Gunicorn to reload).

To set a parameter, just assign to it. There's no special syntax. The values
you provide will be used for the configuration values.

For instance::

    import multiprocessing

    bind = "127.0.0.1:8000"
    workers = multiprocessing.cpu_count() * 2 + 1

All the settings are mentioned in the :ref:`settings <settings>` list.


Framework Settings
==================

Currently, only Paster applications have access to framework specific
settings. If you have ideas for providing settings to WSGI applications or
pulling information from Django's settings.py feel free to open an issue_ to
let us know.

.. _issue: http://github.com/benoitc/gunicorn/issues

Paster Applications
-------------------

In your INI file, you can specify to use Gunicorn as the server like such:

.. code-block:: ini

    [server:main]
    use = egg:gunicorn#main
    host = 192.168.0.1
    port = 80
    workers = 2
    proc_name = brim

Any parameters that Gunicorn knows about will automatically be inserted into
the base configuration. Remember that these will be overridden by the config
file and/or the command line.
