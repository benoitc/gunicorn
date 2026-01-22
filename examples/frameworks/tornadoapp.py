#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.
#
# Run with:
#
#   $ gunicorn -k tornado tornadoapp:app
#

import asyncio
import tornado.ioloop
import tornado.web


class MainHandler(tornado.web.RequestHandler):
    async def get(self):
        # Your asynchronous code here
        await asyncio.sleep(1)  # Example of an asynchronous operation
        self.write("Hello, World!")


def make_app():
    return tornado.web.Application([
        (r"/", MainHandler),
    ])


app = make_app()


if __name__ == "__main__":
    app.listen(8888)
    tornado.ioloop.IOLoop.current().start()
