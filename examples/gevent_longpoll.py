# -*- coding: utf-8 -
#
# This file is part of grainbows released under the MIT license. 
# See the NOTICE for more information.


import time
class TestIter(object):
    
    def __iter__(self):
        lines = ['line 1', 'line 2']
        for line in lines:
            yield line
            time.sleep(10)

def app(environ, start_response):
    """Application which cooperatively pauses 10 seconds before responding"""
    data = 'Hello, World!\n'
    status = '200 OK'
    response_headers = [
        ('Content-type','text/plain'),
        ('Transfer-Encoding', "chunked"),
    ]
    print 'request received'
    start_response(status, response_headers)
    return TestIter()
