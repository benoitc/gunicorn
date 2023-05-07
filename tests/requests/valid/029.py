from gunicorn.config import Config

cfg = Config()

request = {
    "method": "GET",
    "uri": uri("/stuff/here?foo=bar"),
    "version": (1, 1),
    "headers": [
        ('TRANSFER-ENCODING', 'chunked'),
        ('TRANSFER-ENCODING', 'identity')
    ],
    "body": b"hello"
}
