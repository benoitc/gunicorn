from gunicorn.http.errors import LimitRequestHeaders

request = LimitRequestHeaders
cfg.set('limit_request_field_size', 14)

# once this option is removed, this test should not be dropped;
#  rather, add something involving unnessessary padding
cfg.set('permit_obsolete_folding', True)
