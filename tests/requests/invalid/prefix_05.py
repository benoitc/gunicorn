from gunicorn.config import Config
from gunicorn.http.errors import InvalidRequestMethod

cfg = Config()
request = InvalidRequestMethod
