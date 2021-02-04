request = {
    "method": "GET",
    "uri": uri("/unusual_content_length"),
    "version": (1, 0),
    "headers": [
        ("CONTENT-LENGTH", "5")
    ],
    "body": b"HELLO"
}
