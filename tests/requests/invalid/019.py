from gunicorn.config import Config
from gunicorn.http.errors import InvalidSchemeHeaders

request = InvalidSchemeHeaders
cfg = Config()
cfg.set('forwarded_allow_ips', '*')
