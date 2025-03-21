def app(env, start):
    body = b'DEBIAN\n'
    header = [
        ('CONTENT-LENGTH', str(len(body))),
        ('CONTENT-TYPE', 'text/plain'),
    ]
    start_response("200 OK", header)
    return iter([body])
