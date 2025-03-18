from gunicorn.http.errors import LimitRequestHeaders

request = LimitRequestHeaders
cfg.set('limit_request_field_size', 98)
