#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.

"""Gunicorn configuration for TTIN/TTOU testing."""

bind = "0.0.0.0:8000"
workers = 2
worker_class = "gthread"
threads = 2

# Dirty arbiter config
dirty_apps = [
    "app:UnlimitedTask",
    "app:LimitedTask",  # Has workers=2 attribute
]
dirty_workers = 3
dirty_timeout = 30

# Logging
loglevel = "debug"
accesslog = "-"
errorlog = "-"
