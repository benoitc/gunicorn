from gunicorn.http.errors import InvalidHeaderName

cfg.set("header_map", "refuse")

request = InvalidHeaderName
