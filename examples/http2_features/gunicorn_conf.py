# Gunicorn configuration for HTTP/2 features example

bind = "0.0.0.0:8443"
workers = 2
worker_class = "asgi"

# SSL configuration (required for HTTP/2)
certfile = "/app/certs/server.crt"
keyfile = "/app/certs/server.key"

# HTTP/2 configuration
http_protocols = "h2,h1"
http2_max_concurrent_streams = 100
http2_initial_window_size = 65535
http2_max_frame_size = 16384

# Logging
accesslog = "-"
errorlog = "-"
loglevel = "info"
