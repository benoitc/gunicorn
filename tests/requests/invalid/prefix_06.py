from gunicorn.config import Config
from gunicorn.http.errors import InvalidHTTPVersion

cfg = Config()
request = InvalidHTTPVersion
