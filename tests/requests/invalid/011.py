from gunicorn.http.errors import LimitRequestHeaders

request = LimitRequestHeaders
cfg.set('limit_request_fields', 2)
