from gunicorn.config import Config
from gunicorn.http.errors import InvalidHeader

cfg = Config()
request = InvalidHeader
