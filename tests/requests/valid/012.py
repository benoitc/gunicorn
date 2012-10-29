request = {
    "method": "POST",
    "uri": uri("/chunked_w_trailing_headers"),
    "version": (1, 1),
    "headers": [
        ("TRANSFER-ENCODING", "chunked")
    ],
    "body": b"hello world",
    "trailers": [
        ("VARY", "*"),
        ("CONTENT-TYPE", "text/plain")
    ]
}
