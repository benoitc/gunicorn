# Run with:
#
#   $ python ittyapp.py
#

from itty import *

@get('/')
def index(request):
    return 'Hello World!'

run_itty(server='gunicorn')
