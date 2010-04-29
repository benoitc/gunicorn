# -*- coding: utf-8 -
#
# This file is part of gunicorn released under the MIT license. 
# See the NOTICE for more information.


import os
from setuptools import setup, find_packages

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
    ],
    zip_safe = False,
    packages = find_packages(exclude=['examples', 'tests']),
    include_package_data = True,
    
    install_requires=['setuptools'],
    
        
    entry_points="""
    
    [console_scripts]
    gunicorn=gunicorn.main:run
    gunicorn_django=gunicorn.main:run_django
    gunicorn_paster=gunicorn.main:run_paster

    [gunicorn.workers]
    sync=gunicorn.workers.sync:SyncWorker
    eventlet=gunicorn.workers.geventlet:EventletWorker
    gevent=gunicorn.workers.ggevent:GEventWorker
    tornado=gunicorn.workers.gtornado:TornadoWorker

    [paste.server_runner]
    main=gunicorn.main:paste_server
    """,
    test_suite = 'nose.collector',
)
