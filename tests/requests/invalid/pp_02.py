from gunicorn.config import Config
from gunicorn.http.errors import InvalidProxyLine

cfg = Config()
cfg.set('proxy_protocol', True)

request = InvalidProxyLine
