request = {
    "method": "GET",
    "uri": uri("/keep/same/as?invalid/040"),
    "version": (1, 0),
    "headers": [
        ("CONTENT-LENGTH", "7"),
    ],
    "body": b'tricked',
}
