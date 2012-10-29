request = {
    "method": "GET",
    "uri": uri("/first"),
    "version": (1, 0),
    "headers": [('CONTENT-LENGTH', '24')],
    "body": b"GET /second HTTP/1.1\r\n\r\n"
}
