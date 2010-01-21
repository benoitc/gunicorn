# -*- coding: utf-8 -
#
# This file is part of gunicorn released under the MIT license. 
# See the NOTICE for more information.


import os
from setuptools import setup, find_packages

setup(
    name = 'gunicorn',
    version = '0.2',

    description = 'WSGI HTTP Server for UNIX',
    long_description = file(
        os.path.join(
            os.path.dirname(__file__),
            'README.rst'
        )
    ).read(),
    author = 'Benoit Chesneau',
    author_email = 'benoitc@e-engura.com',
    license = 'Apache License 2',
    url = 'http://github.com/benoitc/gunicorn',

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
    
    packages = find_packages(),
    include_package_data = True,
    scripts = ['bin/gunicorn', 'bin/gunicorn_django'],
    
    test_suite = 'nose.collector',

)

