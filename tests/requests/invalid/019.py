from gunicorn.http.errors import InvalidSchemeHeaders

request = InvalidSchemeHeaders
cfg.set('forwarded_allow_ips', '*')
