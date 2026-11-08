#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.

"""Print the version and location of the gunicorn that _launch.py imports."""

import os

import gunicorn

print(gunicorn.__version__, os.path.dirname(gunicorn.__file__))
