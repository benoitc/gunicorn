
raise RuntimeError("Bad app!")

def app(environ, start_response):
    assert 1 == 2, "Shouldn't get here."
