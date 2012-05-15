import logging

from pylons import request, response, session, tmpl_context as c
from pylons.controllers.util import abort

from pylonstest.lib.base import BaseController, render

log = logging.getLogger(__name__)

class HelloController(BaseController):

    def index(self):
        # Return a rendered template
        #return render('/hello.mako')
        # or, return a response
        return 'Hello World'
