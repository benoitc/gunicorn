# -*- coding: utf-8 -
#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.

<<<<<<< HEAD
version_info = (20, 1, 0)
=======
version_info = (19, 10, 0)
>>>>>>> origin/19.x
__version__ = ".".join([str(v) for v in version_info])
SERVER = "gunicorn"
SERVER_SOFTWARE = "%s/%s" % (SERVER, __version__)
