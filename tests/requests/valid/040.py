from gunicorn.config import Config
cfg = Config()
cfg.set("header_map", "drop")

request = {
    "method": "GET",
    "uri": uri("/keep/same/as?invalid/040"),
    "version": (1, 0),
    "headers": [
        ("CONTENT-LENGTH", "7")
    ],
    "body": b'tricked'
}
