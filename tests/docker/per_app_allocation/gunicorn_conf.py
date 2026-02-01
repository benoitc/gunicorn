#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.

"""
Gunicorn configuration for per-app worker allocation e2e tests.

Configuration:
- 4 dirty workers total
- LightweightApp: loads on ALL 4 workers (workers=None)
- HeavyApp: loads on 2 workers (via class attribute workers=2)
- ConfigLimitedApp: loads on 1 worker (via config :1 suffix)
"""

bind = "0.0.0.0:8000"
workers = 1  # HTTP workers
worker_class = "sync"

# 4 dirty workers - enough to test distribution
dirty_workers = 4

# App configuration:
# - LightweightApp: no limit, loads on all 4
# - HeavyApp: workers=2 class attribute, loads on 2
# - ConfigLimitedApp: config override :1, loads on 1
dirty_apps = [
    "app:LightweightApp",
    "app:HeavyApp",
    "app:ConfigLimitedApp:1",
]

dirty_timeout = 30
dirty_graceful_timeout = 5
timeout = 30
graceful_timeout = 5
loglevel = "debug"
accesslog = "-"
errorlog = "-"
