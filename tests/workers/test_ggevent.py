#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.

def test_import():
    __import__('gunicorn.workers.ggevent')
