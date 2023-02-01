from gunicorn.config import Config
from gunicorn.ghttp.errors import InvalidSchemeHeaders

request = InvalidSchemeHeaders
cfg = Config()
cfg.set('forwarded_allow_ips', '*')
