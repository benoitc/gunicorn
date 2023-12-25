from gunicorn.http.errors import InvalidHeaderName
from gunicorn.config import Config

cfg = Config()
cfg.set("header_map", "refuse")

request = InvalidHeaderName
