#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.

bind = "0.0.0.0:8000"
workers = 2
worker_class = "asgi"

# Dirty worker config
dirty_apps = ["streaming_chat.chat_app:ChatApp"]
dirty_workers = 1
dirty_timeout = 60
