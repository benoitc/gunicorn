from gunicorn.config import Config
from gunicorn.http.errors import LimitRequestLine
cfg = Config()
cfg.set("limit_request_line", 4094)
request = LimitRequestLine
