request = {
    "method": "GET",
    "uri": uri("scheme+ext://user+ext:password!@[::1]:8000/path?query#frag"),
    "version": (1, 1),
    "headers": [
        ("HOST", "localhost"),
        ("CONTENT-LENGTH", "3"),
    ],
    "body": b'odd'
}
