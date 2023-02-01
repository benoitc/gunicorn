from gunicorn.config import Config
from gunicorn.ghttp.errors import InvalidProxyLine

cfg = Config()
cfg.set('proxy_protocol', True)

request = InvalidProxyLine
