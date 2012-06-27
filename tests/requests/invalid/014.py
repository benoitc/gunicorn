from gunicorn.config import Config
from gunicorn.http.errors import InvalidProxyLine

cfg = Config()
cfg.set('auto_proxy', True)

request = InvalidProxyLine
