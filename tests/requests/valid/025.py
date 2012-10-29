req1 = {
    "method": "POST",
    "uri": uri("/chunked_cont_h_at_first"),
    "version": (1, 1),
    "headers": [
        ("CONTENT-LENGTH", "-1"),
        ("TRANSFER-ENCODING", "chunked")
    ],
    "body": b"hello world"
}

req2 = {
    "method": "PUT",
    "uri": uri("/chunked_cont_h_at_last"),
    "version": (1, 1),
    "headers": [
        ("TRANSFER-ENCODING", "chunked"),
        ("CONTENT-LENGTH", "-1"),
    ],
    "body": b"hello world"
}

request = [req1, req2]
