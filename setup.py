# -*- coding: utf-8 -
#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.

import os
import sys

from setuptools import setup, find_packages
from setuptools.command.test import test as TestCommand

from gunicorn import __version__


CLASSIFIERS = [
    'Development Status :: 5 - Production/Stable',
    'Environment :: Other Environment',
    'Intended Audience :: Developers',
    'License :: OSI Approved :: MIT License',
    'Operating System :: MacOS :: MacOS X',
    'Operating System :: POSIX',
    'Programming Language :: Python',
    'Programming Language :: Python :: 3',
    'Programming Language :: Python :: 3.5',
    'Programming Language :: Python :: 3.6',
    'Programming Language :: Python :: 3.7',
    'Programming Language :: Python :: 3.8',
    'Programming Language :: Python :: 3.9',
    'Programming Language :: Python :: 3.10',
    'Programming Language :: Python :: 3 :: Only',
    'Programming Language :: Python :: Implementation :: CPython',
    'Programming Language :: Python :: Implementation :: PyPy',
    'Topic :: Internet',
    'Topic :: Utilities',
    'Topic :: Software Development :: Libraries :: Python Modules',
    'Topic :: Internet :: WWW/HTTP',
    'Topic :: Internet :: WWW/HTTP :: WSGI',
    'Topic :: Internet :: WWW/HTTP :: WSGI :: Server',
    'Topic :: Internet :: WWW/HTTP :: Dynamic Content']

# read long description
with open(os.path.join(os.path.dirname(__file__), 'README.rst')) as f:
    long_description = f.read()

# read dev requirements
fname = os.path.join(os.path.dirname(__file__), 'requirements_test.txt')
with open(fname) as f:
    tests_require = [l.strip() for l in f.readlines()]

class PyTestCommand(TestCommand):
    user_options = [
        ("cov", None, "measure coverage")
    ]

    def initialize_options(self):
        TestCommand.initialize_options(self)
        self.cov = None

    def finalize_options(self):
        TestCommand.finalize_options(self)
        self.test_args = ['tests']
        if self.cov:
            self.test_args += ['--cov', 'gunicorn']
        self.test_suite = True

    def run_tests(self):
        import pytest
        errno = pytest.main(self.test_args)
        sys.exit(errno)


install_requires = [
    # We depend on functioning pkg_resources.working_set.add_entry() and
    # pkg_resources.load_entry_point(). These both work as of 3.0 which
    # is the first version to support Python 3.4 which we require as a
    # floor.
    'setuptools>=3.0',
    'packaging',
]

extras_require = {
    'gevent':  ['gevent>=1.4.0'],
    'eventlet': ['eventlet>=0.24.1'],
    'tornado': ['tornado>=0.2'],
    'gthread': [],
    'setproctitle': ['setproctitle'],
}

setup(
    name='gunicorn',
    version=__version__,

    description='WSGI HTTP Server for UNIX',
    long_description=long_description,
    author='Benoit Chesneau',
    author_email='benoitc@gunicorn.org',
    license='MIT',
    url='https://gunicorn.org',
    project_urls={
        'Documentation': 'https://docs.gunicorn.org',
        'Homepage': 'https://gunicorn.org',
        'Issue tracker': 'https://github.com/benoitc/gunicorn/issues',
        'Source code': 'https://github.com/benoitc/gunicorn',
    },

    python_requires='>=3.5',
    install_requires=install_requires,
    classifiers=CLASSIFIERS,
    zip_safe=False,
    packages=find_packages(exclude=['examples', 'tests']),
    include_package_data=True,

    tests_require=tests_require,
    cmdclass={'test': PyTestCommand},

    entry_points="""
    [console_scripts]
    gunicorn=gunicorn.app.wsgiapp:run

    [paste.server_runner]
    main=gunicorn.app.pasterapp:serve
    """,
    extras_require=extras_require,
)
