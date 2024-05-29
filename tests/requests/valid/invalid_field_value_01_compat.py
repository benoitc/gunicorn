from gunicorn.config import Config

cfg = Config()
cfg.set("tolerate_dangerous_framing", True)

req1 = {
    "method": "GET",
    "uri": uri("/"),
    "version": (1, 1),
    "headers": [
        ("HOST", "x"),
        ("NEWLINE", "a\nContent-Length: 26"),
        ("X-FORWARDED-BY", "broken-proxy"),
    ],
    "body": b""
}

request = [req1]
