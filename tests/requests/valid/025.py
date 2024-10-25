request = {
    "method": "POST",
    "uri": uri("/chunked"),
    "version": (1, 1),
    "headers": [
        ('TRANSFER-ENCODING', 'gzip'),
        ('TRANSFER-ENCODING', 'chunked'),
    ],
    "body": b"hello world",
}
