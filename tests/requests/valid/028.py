cfg.set("strip_header_spaces", True)

request = {
    "method": "GET",
    "uri": uri("/stuff/here?foo=bar"),
    "version": (1, 1),
    "headers": [
        ("CONTENT-LENGTH", "3"),
    ],
    "body": b"xyz",
}
