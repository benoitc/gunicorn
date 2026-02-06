#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.

# Run with:
#
#   $ gunicorn flaskapp:app
#

from flask import Flask
app = Flask(__name__)

@app.route("/")
def hello():
    return "Hello World!"
