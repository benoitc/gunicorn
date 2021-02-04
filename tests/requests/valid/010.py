request = {
    "method": "POST",
    "uri": uri("/post_chunked_all_your_base"),
    "version": (1, 1),
    "headers": [
        ("TRANSFER-ENCODING", "chunked"),
    ],
    "body": b"all your base are belong to us"
}
