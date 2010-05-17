# -*- coding: utf-8 -
#
# This file is part of gunicorn released under the MIT license. 
# See the NOTICE for more information.
    
def run():
    """\
    The ``gunicorn`` command line runner for launcing Gunicorn with
    generic WSGI applications.
    """
    from gunicorn.app.wsgiapp import WSGIApplication
    WSGIApplication("%prog [OPTIONS] APP_MODULE").run()
    
def run_django():
    """\
    The ``gunicorn_django`` command line runner for launching Django
    applications.
    """
    from gunicorn.app.djangoapp import DjangoApplication
    DjangoApplication("%prog [OPTIONS] [SETTINGS_PATH]").run()
    
def run_paster():
    """\
    The ``gunicorn_paster`` command for launcing Paster compatible
    apllications like Pylons or Turbogears2
    """
    from gunicorn.app.pasterapp import PasterApplication
    PasterApplication("%prog [OPTIONS] pasteconfig.ini").run()

def paste_server(app, gcfg=None, host="127.0.0.1", port=None, *args, **kwargs):
    """\
    A paster server.
    
    Then entry point in your paster ini file should looks like this:
    
    [server:main]
    use = egg:gunicorn#main
    host = 127.0.0.1
    port = 5000
    
    """
    from gunicorn.app.pasterapp import PasterServerApplication
    PasterServerApplication(app, gcfg=gcfg, host=host, port=port, *args, **kwargs).run()

 


