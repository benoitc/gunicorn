# -*- coding: utf-8 -
#
# This file is part of gunicorn released under the MIT license. 
# See the NOTICE for more information.

import os
import t

from gunicorn.http import tee

@t.http_request("001.http")
def test_001(req):
    e = req.read()
    t.eq(e['CONTENT_LENGTH'], '14')
    t.eq(e['wsgi.version'], (1,0))
    t.eq(e['REQUEST_METHOD'], 'PUT')
    t.eq(e['PATH_INFO'], '/stuff/here')
    t.eq(e['CONTENT_TYPE'], 'application/json')
    t.eq(e['QUERY_STRING'], 'foo=bar')
    
    t.eq(isinstance(e['wsgi.input'], tee.TeeInput), True)
    body = e['wsgi.input'].read()
    t.eq(body, '{"nom": "nom"}')

@t.http_request("002.http")
def test_002(req):
    e = req.read()
    t.eq(e['REQUEST_METHOD'], 'GET')
    t.eq(e['PATH_INFO'], "/test")
    t.eq(e['QUERY_STRING'], "")
    t.eq(e['HTTP_ACCEPT'], "*/*")
    t.eq(e['HTTP_HOST'], "0.0.0.0=5000")
    t.eq(e['HTTP_USER_AGENT'], "curl/7.18.0 (i486-pc-linux-gnu) libcurl/7.18.0 OpenSSL/0.9.8g zlib/1.2.3.3 libidn/1.1")
    body = e['wsgi.input'].read()
    t.eq(body, '')

@t.http_request("003.http")
def test_003(req):
    e = req.read()
    
    t.eq(e['REQUEST_METHOD'], 'GET')
    t.eq(e['PATH_INFO'], "/favicon.ico")
    t.eq(e['QUERY_STRING'], "")
    t.eq(e['HTTP_ACCEPT'], "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8")
    t.eq(e['HTTP_KEEP_ALIVE'], "300")

    body = e['wsgi.input'].read()
    t.eq(body, '')

@t.http_request("004.http")
def test_004(req):
    e = req.read()
    t.eq(e['REQUEST_METHOD'], 'GET')
    t.eq(e['PATH_INFO'], "/dumbfuck")
    t.eq(e['QUERY_STRING'], "")
    body = e['wsgi.input'].read()
    t.eq(body, '')


@t.http_request("005.http")
def test_005(req):
    e = req.read()
    t.eq(e['REQUEST_METHOD'], 'GET')
    t.eq(e['PATH_INFO'], "/forums/1/topics/2375")
    t.eq(e['QUERY_STRING'], "page=1")
    body = e['wsgi.input'].read()
    t.eq(body, '')


@t.http_request("006.http")
def test_006(req):
    e = req.read()
    t.eq(e['REQUEST_METHOD'], 'GET')
    t.eq(e['PATH_INFO'], "/get_no_headers_no_body/world")
    t.eq(e['QUERY_STRING'], "")
    body = e['wsgi.input'].read()
    t.eq(body, '')


@t.http_request("007.http")
def test_007(req):
    e = req.read()
    t.eq(e['REQUEST_METHOD'], 'GET')
    t.eq(e['PATH_INFO'], "/get_one_header_no_body")
    t.eq(e['QUERY_STRING'], "")
    t.eq(e['HTTP_ACCEPT'], "*/*")
    body = e['wsgi.input'].read()
    t.eq(body, '')

    
@t.http_request("008.http")
def test_008(req):
    e = req.read()
    t.eq(e['REQUEST_METHOD'], 'GET')
    t.eq(e['PATH_INFO'], "/get_funky_content_length_body_hello")
    t.eq(e['QUERY_STRING'], "")
    t.eq(e['CONTENT_LENGTH'], '5')
    body = e['wsgi.input'].read()
    t.eq(body, "HELLO")
    

@t.http_request("009.http")
def test_009(req):
    e = req.read()
    t.eq(e['REQUEST_METHOD'], 'POST')
    t.eq(e['PATH_INFO'], "/post_identity_body_world")
    t.eq(e['QUERY_STRING'], "q=search")
    t.eq(e['CONTENT_LENGTH'], '5')
    body = e['wsgi.input'].read()
    t.eq(body, "World")


@t.http_request("010.http")
def test_010(req):
    e = req.read()
    t.eq(e['REQUEST_METHOD'], 'POST')
    t.eq(e['PATH_INFO'], "/post_chunked_all_your_base")
    t.eq(e['HTTP_TRANSFER_ENCODING'], "chunked")
    t.eq(e['CONTENT_LENGTH'], '30')
    body = e['wsgi.input'].read()
    t.eq(body, "all your base are belong to us")

    
@t.http_request("011.http")
def test_011(req):
    e = req.read()
    t.eq(e['REQUEST_METHOD'], 'POST')
    t.eq(e['PATH_INFO'], "/two_chunks_mult_zero_end")
    t.eq(e['HTTP_TRANSFER_ENCODING'], "chunked")
    t.eq(e['CONTENT_LENGTH'], '11')
    body = e['wsgi.input'].read()
    t.eq(body, "hello world")
    
@t.http_request("017.http")
def test_017(req):
    e = req.read()
    t.eq(e['REQUEST_METHOD'], 'GET')
    t.eq(e['PATH_INFO'], "/stuff/here")
    t.eq(e["HTTP_IF_MATCH"], "bazinga!, large-sound")
    t.eq(e["wsgi.input"].read(), "")
    
@t.http_request("017.http")
def test_018(req):
    os.environ['SCRIPT_NAME'] = "/stuff"
    e = req.read()
    t.eq(e['REQUEST_METHOD'], 'GET')
    t.eq(e['SCRIPT_NAME'], "/stuff")
    t.eq(e['PATH_INFO'], "/here")
    t.eq(e["wsgi.input"].read(), "")
    

