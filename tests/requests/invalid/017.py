from gunicorn.config import Config
from gunicorn.ghttp.errors import LimitRequestHeaders

cfg = Config()
request = LimitRequestHeaders
