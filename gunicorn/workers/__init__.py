#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.

# supported gunicorn workers.
SUPPORTED_WORKERS = {
    "sync": "gunicorn.workers.sync.SyncWorker",
    "eventlet": "gunicorn.workers.geventlet.EventletWorker",  # DEPRECATED: will be removed in 26.0
    "gevent": "gunicorn.workers.ggevent.GeventWorker",
    "gevent_wsgi": "gunicorn.workers.ggevent.GeventPyWSGIWorker",
    "gevent_pywsgi": "gunicorn.workers.ggevent.GeventPyWSGIWorker",
    "tornado": "gunicorn.workers.gtornado.TornadoWorker",
    "gthread": "gunicorn.workers.gthread.ThreadWorker",
    "asgi": "gunicorn.workers.gasgi.ASGIWorker",
}
