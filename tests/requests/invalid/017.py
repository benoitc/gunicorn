from gunicorn.config import Config
from gunicorn.http.errors import LimitRequestHeaders

cfg = Config()
request = LimitRequestHeaders
