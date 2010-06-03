req1 = {
    "method": "GET",
    "uri": uri("/first"),
    "version": (1, 0),
    "headers": [("CONNECTION", "Keep-Alive")],
    "body": ""
}

req2 = {
    "method": "GET",
    "uri": uri("/second"),
    "version": (1, 1),
    "headers": [],
    "body": ""
}

request = [req1, req2]