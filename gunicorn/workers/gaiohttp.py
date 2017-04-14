# -*- coding: utf-8 -
#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.

import sys
from gunicorn import utils

if sys.version_info >= (3, 4):
    try:
        import aiohttp  # NOQA
    except ImportError:
        raise RuntimeError("You need aiohttp installed to use this worker.")
    else:
        try:
            from aiohttp.worker import GunicornWebWorker as AiohttpWorker
        except ImportError:
            from gunicorn.workers._gaiohttp import AiohttpWorker

            utils.warn(
                "AiohttpWorker is deprecated please install aiohttp 1.2+ "
                "and set aiohttp.worker.GunicornWebWorker as a custom worker ")

        __all__ = ['AiohttpWorker']
else:
    raise RuntimeError("You need Python >= 3.4 to use the asyncio worker")
