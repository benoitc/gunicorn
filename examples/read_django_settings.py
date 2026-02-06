#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.

"""
Use this config file in your script like this:

    $ gunicorn project_name.wsgi:application -c read_django_settings.py
"""

settings_dict = {}

with open('frameworks/django/testing/testing/settings.py') as f:
    exec(f.read(), settings_dict)

loglevel = 'warning'
proc_name = 'web-project'
workers = 1

if settings_dict['DEBUG']:
    loglevel = 'debug'
    reload = True
    proc_name += '_debug'
