request = {
    "method": "POST",
    "uri": uri("/chunked"),
    "version": (1, 1),
    "headers": [
        ('TRANSFER-ENCODING', 'identity'),
        ('TRANSFER-ENCODING', 'chunked')
    ],
    "body": b"hello world"
}
