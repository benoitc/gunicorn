request = {
    "method": "POST",
    "uri": uri("/chunked_w_extensions"),
    "version": (1, 1),
    "headers": [
        ("TRANSFER-ENCODING", "chunked")
    ],
    "body": b"hello world"
}
