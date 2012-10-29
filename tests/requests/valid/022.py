req1 = {
    "method": "GET",
    "uri": uri("/first"),
    "version": (1, 0),
    "headers": [("CONNECTION", "Keep-Alive")],
    "body": b""
}

req2 = {
    "method": "GET",
    "uri": uri("/second"),
    "version": (1, 1),
    "headers": [],
    "body": b""
}

request = [req1, req2]
