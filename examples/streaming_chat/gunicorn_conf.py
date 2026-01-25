bind = "0.0.0.0:8000"
workers = 2
worker_class = "asgi"

# Dirty worker config
dirty_apps = ["streaming_chat.chat_app:ChatApp"]
dirty_workers = 1
dirty_timeout = 60
