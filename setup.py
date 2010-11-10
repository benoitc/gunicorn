# -*- coding: utf-8 -
#
# This file is part of gunicorn released under the MIT license. 
# See the NOTICE for more information.


import os
from setuptools import setup, find_packages
import sys

from gunicorn import __version__


try:#python 2.6, use subprocess
    import subprocess
    subprocess.Popen  # trigger ImportError early
    closefds = os.name == 'posix'
    
    def popen3(cmd, mode='t', bufsize=0):
        p = subprocess.Popen(cmd, shell=True, bufsize=bufsize,
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, 
            close_fds=closefds)
        p.wait()
        return (p.stdin, p.stdout, p.stderr)
except ImportError:
    subprocess = None
    popen3 = os.popen3


DEVELOP = "develop" in sys.argv

version = __version__
if DEVELOP:
    minor_tag = ""
    try:
        stdin, stdout, stderr = popen3("git rev-parse --short HEAD --")
        error = stderr.read()
        if not error:
            git_tag = stdout.read()[:-1]
            minor_tag = ".%s-git" % git_tag
    except OSError:        
        pass

    version = "%s%s" % (version, minor_tag)


setup(
    name = 'gunicorn',
    version = version,

    description = 'WSGI HTTP Server for UNIX',
    long_description = file(
        os.path.join(
            os.path.dirname(__file__),
            'README.rst'
        )
    ).read(),
    author = 'Benoit Chesneau',
    author_email = 'benoitc@e-engura.com',
    license = 'MIT',
    url = 'http://gunicorn.org',

    classifiers = [
        'Development Status :: 4 - Beta',
        'Environment :: Other Environment',
        'Intended Audience :: Developers',
        'License :: OSI Approved :: MIT License',
        'Operating System :: MacOS :: MacOS X',
        'Operating System :: POSIX',
        'Programming Language :: Python',
        'Topic :: Internet',
        'Topic :: Utilities',
        'Topic :: Software Development :: Libraries :: Python Modules',
    ],
    zip_safe = False,
    packages = find_packages(exclude=['examples', 'tests']),
    include_package_data = True,
    
    install_requires=['setuptools'],

    entry_points="""
    
    [console_scripts]
    gunicorn=gunicorn.app.wsgiapp:run
    gunicorn_django=gunicorn.app.djangoapp:run
    gunicorn_paster=gunicorn.app.pasterapp:run

    [gunicorn.workers]
    sync=gunicorn.workers.sync:SyncWorker
    eventlet=gunicorn.workers.geventlet:EventletWorker
    gevent=gunicorn.workers.ggevent:GeventWorker
    gevent_wsgi=gunicorn.workers.ggevent:GeventWSGIWorker
    gevent_pywsgi=gunicorn.workers.ggevent:GeventPyWSGIWorker
    tornado=gunicorn.workers.gtornado:TornadoWorker

    [paste.server_runner]
    main=gunicorn.app.pasterapp:paste_server
    """,
    test_suite = 'nose.collector',
)
