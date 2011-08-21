import logging

log = logging.getLogger(__name__)

log.addHandler(logging.StreamHandler())

def app_factory(global_options, **local_options):
    return app

def app(environ, start_response):
    start_response("200 OK", [])
    log.debug("Hello Debug!")
    log.info("Hello Info!")
    log.warn("Hello Warn!")
    log.error("Hello Error!")
    return ["Hello World!\n"]
