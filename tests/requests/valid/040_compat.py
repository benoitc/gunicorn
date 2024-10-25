cfg.set("header_map", "dangerous")

request = {
    "method": "GET",
    "uri": uri("/keep/same/as?invalid/040"),
    "version": (1, 0),
    "headers": [
        ("TRANSFER_ENCODING", "tricked"),
        ("CONTENT-LENGTH", "7"),
        ("CONTENT_LENGTH", "-1E23"),
    ],
    "body": b'tricked',
}
