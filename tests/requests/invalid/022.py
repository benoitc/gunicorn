from gunicorn.config import Config
from gunicorn.http.errors import UnsupportedTransferEncoding

cfg = Config()
request = UnsupportedTransferEncoding
