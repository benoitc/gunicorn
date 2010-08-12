# -*- coding: utf-8 -
#
# This file is part of gunicorn released under the MIT license. 
# See the NOTICE for more information.


import os

if os.environ.get('release') != "true":

    minor_tag = ""
    try:
        from gunicorn.util import popen3

        stdin, stdout, stderr = popen3("git rev-parse --short HEAD --")
        error = stderr.read()
        if not error:
            git_tag = stdout.read()[:-1]
            minor_tag = ".%s-git" % git_tag
    except OSError:        
        pass
else:
    minor_tag = ""
    

version_info = (0, 11, "0%s" % minor_tag)
__version__ = ".".join(map(str, version_info))
