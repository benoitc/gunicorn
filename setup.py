# -*- coding: utf-8 -
#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.


import os
from setuptools import setup, find_packages
import sys

from gunicorn import __version__

setup(
    name = 'gunicorn',
    version = __version__,

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
        'Topic :: Internet :: WWW/HTTP',
        'Topic :: Internet :: WWW/HTTP :: WSGI',
        'Topic :: Internet :: WWW/HTTP :: WSGI :: Server',
        'Topic :: Internet :: WWW/HTTP :: Dynamic Content',
    ],
    zip_safe = False,
    packages = find_packages(exclude=['examples', 'tests']),
    include_package_data = True,

    entry_points="""

    [console_scripts]
    gunicorn=gunicorn.app.wsgiapp:run
    gunicorn_django=gunicorn.app.djangoapp:run
    gunicorn_paster=gunicorn.app.pasterapp:run

    [gunicorn.workers]
    sync=gunicorn.workers.sync:SyncWorker
    eventlet=gunicorn.workers.geventlet:EventletWorker
    gevent=gunicorn.workers.ggevent:GeventWorker
    gevent_wsgi=gunicorn.workers.ggevent:GeventPyWSGIWorker
    gevent_pywsgi=gunicorn.workers.ggevent:GeventPyWSGIWorker
    tornado=gunicorn.workers.gtornado:TornadoWorker

    [gunicorn.loggers]
    simple=gunicorn.glogging:Logger

    [paste.server_runner]
    main=gunicorn.app.pasterapp:paste_server
    """,
    test_suite = 'nose.collector',
)
