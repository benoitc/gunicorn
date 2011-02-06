request = {
    "method": "GET",
    "uri": uri("/test"),
    "scheme": "https",
    "version": (1, 0),
    "headers": [
        ("HOST", "0.0.0.0:5000"),
        ("USER-AGENT", "ApacheBench/2.3"),
        ("ACCEPT", "*/*"),
        ("HTTPS", "on")
    ],
    "body": ""
}
