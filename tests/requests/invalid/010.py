from gunicorn.config import Config
from gunicorn.http.errors import LimitRequestHeaders

request = LimitRequestHeaders
cfg = Config()
cfg.set('limit_request_field_size', 10)
