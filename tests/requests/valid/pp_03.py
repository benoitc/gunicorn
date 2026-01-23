from gunicorn.config import Config

cfg = Config()
cfg.set("proxy_protocol", True)

request = {
    "method": "GET",
    "uri": uri("/no/proxy/header"),
    "version": (1, 1),
    "headers": [
        ("HOST", "example.com"),
        ("CONTENT-LENGTH", "0")
    ],
    "body": b""
}
