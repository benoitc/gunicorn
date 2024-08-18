cfg.set("permit_unconventional_http_method", True)

request = {
    "method": "-blargh",
    "uri": uri("/foo"),
    "version": (1, 1),
    "headers": [],
    "body": b"",
}
