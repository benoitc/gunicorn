#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.

"""
Gunicorn configuration for integration tests.
"""

bind = "0.0.0.0:8000"
workers = 1
worker_class = "sync"
dirty_workers = 1
dirty_apps = ["app:TestDirtyApp"]
dirty_timeout = 30
dirty_graceful_timeout = 5
timeout = 30
graceful_timeout = 5
loglevel = "debug"
accesslog = "-"
errorlog = "-"
