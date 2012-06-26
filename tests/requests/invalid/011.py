from gunicorn.config import Config
from gunicorn.http.errors import LimitRequestHeaders

request = LimitRequestHeaders
cfg = Config()
cfg.set('limit_request_fields', 2)
