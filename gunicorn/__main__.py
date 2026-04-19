#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.

import runpy
import sys

from gunicorn.app.wsgiapp import run

if __name__ == "__main__":
    # Run as a module: python -m gunicorn
    # Use runpy to properly set argv[0] for argparse
    sys.argv[0] = "gunicorn"
    run(prog="gunicorn")
