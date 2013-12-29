request = {
    "method": "POST",
    "uri": uri("/test-form"),
    "version": (1, 1),
    "headers": [
        ("HOST", "0.0.0.0:5000"),
        ("USER-AGENT", "Mozilla/5.0 (Windows NT 6.2; WOW64; rv:25.0) Gecko/20100101 Firefox/25.0"),
        ("ACCEPT", "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"),
        ("ACCEPT-LANGUAGE", "en-us,en;q=0.7,el;q=0.3"),
        ("ACCEPT-ENCODING", "gzip, deflate"),
        ("COOKIE", "csrftoken=XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX; sessionid=YYYYYYYYYYYYYYYYYYYYYYYYYYYY"),
        ("CONNECTION", "keep-alive"),
        ("CONTENT-TYPE", "multipart/form-data; boundary=---------------------------320761477111544"),
        ("CONTENT-LENGTH", "17914"),
    ],
    "body": b"""-----------------------------320761477111544\r\n
Content-Disposition: form-data; name="csrfmiddlewaretoken"\r\n
\r\n
XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX\r\n
-----------------------------320761477111544\r\n
Content-Disposition: form-data; name="_save"\r\n
\r\n
Save\r\n
-----------------------------320761477111544\r\n
Content-Disposition: form-data; name="name"\r\n
\r\n
test.example.org\r\n
-----------------------------320761477111544\r\n
Content-Disposition: form-data; name="type"\r\n
\r\n
NATIVE\r\n
-----------------------------320761477111544\r\n
Content-Disposition: form-data; name="master"\r\n
\r\n
\r\n
-----------------------------320761477111544\r\n
Content-Disposition: form-data; name="foobar_manager_dynamiczone_domain-TOTAL_FORMS"\r\n
\r\n
1\r\n
-----------------------------320761477111544\r\n
Content-Disposition: form-data; name="foobar_manager_dynamiczone_domain-INITIAL_FORMS"\r\n
\r\n
1\r\n
-----------------------------320761477111544\r\n
Content-Disposition: form-data; name="foobar_manager_dynamiczone_domain-MAX_NUM_FORMS"\r\n
\r\n
1\r\n
-----------------------------320761477111544\r\n
Content-Disposition: form-data; name="foobar_manager_dynamiczone_domain-0-is_dynamic"\r\n
\r\n
on\r\n
-----------------------------320761477111544\r\n
Content-Disposition: form-data; name="foobar_manager_dynamiczone_domain-0-id"\r\n
\r\n
1\r\n
-----------------------------320761477111544\r\n
Content-Disposition: form-data; name="foobar_manager_dynamiczone_domain-0-domain"\r\n
\r\n
2\r\n
-----------------------------320761477111544\r\n
Content-Disposition: form-data; name="foobar_manager_dynamiczone_domain-__prefix__-id"\r\n
\r\n
\r\n
-----------------------------320761477111544\r\n
Content-Disposition: form-data; name="foobar_manager_dynamiczone_domain-__prefix__-domain"\r\n
\r\n
2\r\n
-----------------------------320761477111544\r\n
Content-Disposition: form-data; name="foobar_manager_record_domain-TOTAL_FORMS"\r\n
\r\n
1\r\n
-----------------------------320761477111544\r\n
Content-Disposition: form-data; name="foobar_manager_record_domain-INITIAL_FORMS"\r\n
\r\n
1\r\n
-----------------------------320761477111544\r\n
Content-Disposition: form-data; name="foobar_manager_record_domain-MAX_NUM_FORMS"\r\n
\r\n
1\r\n
-----------------------------320761477111544\r\n
Content-Disposition: form-data; name="foobar_manager_record_domain-0-ttl"\r\n
\r\n
3600\r\n
-----------------------------320761477111544\r\n
Content-Disposition: form-data; name="foobar_manager_record_domain-0-primary"\r\n
\r\n
ns.example.org\r\n
-----------------------------320761477111544\r\n
Content-Disposition: form-data; name="foobar_manager_record_domain-0-hostmaster"\r\n
\r\n
hostmaster.test.example.org\r\n
-----------------------------320761477111544\r\n
Content-Disposition: form-data; name="foobar_manager_record_domain-0-serial"\r\n
\r\n
2013121701\r\n
-----------------------------320761477111544\r\n
Content-Disposition: form-data; name="foobar_manager_record_domain-0-refresh"\r\n
\r\n
10800\r\n
-----------------------------320761477111544\r\n
Content-Disposition: form-data; name="foobar_manager_record_domain-0-retry"\r\n
\r\n
3600\r\n
-----------------------------320761477111544\r\n
Content-Disposition: form-data; name="foobar_manager_record_domain-0-expire"\r\n
\r\n
604800\r\n
-----------------------------320761477111544\r\n
Content-Disposition: form-data; name="foobar_manager_record_domain-0-default_ttl"\r\n
\r\n
3600\r\n
-----------------------------320761477111544\r\n
Content-Disposition: form-data; name="foobar_manager_record_domain-0-id"\r\n
\r\n
16\r\n
-----------------------------320761477111544\r\n
Content-Disposition: form-data; name="foobar_manager_record_domain-0-domain"\r\n
\r\n
2\r\n
-----------------------------320761477111544\r\n
Content-Disposition: form-data; name="foobar_manager_record_domain-__prefix__-ttl"\r\n
\r\n
\r\n
-----------------------------320761477111544\r\n
Content-Disposition: form-data; name="foobar_manager_record_domain-__prefix__-primary"\r\n
\r\n
\r\n
-----------------------------320761477111544\r\n
Content-Disposition: form-data; name="foobar_manager_record_domain-__prefix__-hostmaster"\r\n
\r\n
\r\n
-----------------------------320761477111544\r\n
Content-Disposition: form-data; name="foobar_manager_record_domain-__prefix__-serial"\r\n
\r\n
1\r\n
-----------------------------320761477111544\r\n
Content-Disposition: form-data; name="foobar_manager_record_domain-__prefix__-refresh"\r\n
\r\n
10800\r\n
-----------------------------320761477111544\r\n
Content-Disposition: form-data; name="foobar_manager_record_domain-__prefix__-retry"\r\n
\r\n
3600\r\n
-----------------------------320761477111544\r\n
Content-Disposition: form-data; name="foobar_manager_record_domain-__prefix__-expire"\r\n
\r\n
604800\r\n
-----------------------------320761477111544\r\n
Content-Disposition: form-data; name="foobar_manager_record_domain-__prefix__-default_ttl"\r\n
\r\n
3600\r\n
-----------------------------320761477111544\r\n
Content-Disposition: form-data; name="foobar_manager_record_domain-__prefix__-id"\r\n
\r\n
\r\n
-----------------------------320761477111544\r\n
Content-Disposition: form-data; name="foobar_manager_record_domain-__prefix__-domain"\r\n
\r\n
2\r\n
-----------------------------320761477111544\r\n
Content-Disposition: form-data; name="foobar_manager_record_domain-2-TOTAL_FORMS"\r\n
\r\n
0\r\n
-----------------------------320761477111544\r\n
Content-Disposition: form-data; name="foobar_manager_record_domain-2-INITIAL_FORMS"\r\n
\r\n
0\r\n
-----------------------------320761477111544\r\n
Content-Disposition: form-data; name="foobar_manager_record_domain-2-MAX_NUM_FORMS"\r\n
\r\n
1000\r\n
-----------------------------320761477111544\r\n
Content-Disposition: form-data; name="foobar_manager_record_domain-2-__prefix__-id"\r\n
\r\n
\r\n
-----------------------------320761477111544\r\n
Content-Disposition: form-data; name="foobar_manager_record_domain-2-__prefix__-domain"\r\n
\r\n
2\r\n
-----------------------------320761477111544\r\n
Content-Disposition: form-data; name="foobar_manager_record_domain-2-__prefix__-name"\r\n
\r\n
\r\n
-----------------------------320761477111544\r\n
Content-Disposition: form-data; name="foobar_manager_record_domain-2-__prefix__-ttl"\r\n
\r\n
\r\n
-----------------------------320761477111544\r\n
Content-Disposition: form-data; name="foobar_manager_record_domain-2-__prefix__-content"\r\n
\r\n
\r\n
-----------------------------320761477111544\r\n
Content-Disposition: form-data; name="foobar_manager_record_domain-3-TOTAL_FORMS"\r\n
\r\n
0\r\n
-----------------------------320761477111544\r\n
Content-Disposition: form-data; name="foobar_manager_record_domain-3-INITIAL_FORMS"\r\n
\r\n
0\r\n
-----------------------------320761477111544\r\n
Content-Disposition: form-data; name="foobar_manager_record_domain-3-MAX_NUM_FORMS"\r\n
\r\n
1000\r\n
-----------------------------320761477111544\r\n
Content-Disposition: form-data; name="foobar_manager_record_domain-3-__prefix__-id"\r\n
\r\n
\r\n
-----------------------------320761477111544\r\n
Content-Disposition: form-data; name="foobar_manager_record_domain-3-__prefix__-domain"\r\n
\r\n
2\r\n
-----------------------------320761477111544\r\n
Content-Disposition: form-data; name="foobar_manager_record_domain-3-__prefix__-name"\r\n
\r\n
\r\n
-----------------------------320761477111544\r\n
Content-Disposition: form-data; name="foobar_manager_record_domain-3-__prefix__-ttl"\r\n
\r\n
\r\n
-----------------------------320761477111544\r\n
Content-Disposition: form-data; name="foobar_manager_record_domain-3-__prefix__-prio"\r\n
\r\n
\r\n
-----------------------------320761477111544\r\n
Content-Disposition: form-data; name="foobar_manager_record_domain-3-__prefix__-content"\r\n
\r\n
\r\n
-----------------------------320761477111544\r\n
Content-Disposition: form-data; name="foobar_manager_record_domain-4-TOTAL_FORMS"\r\n
\r\n
0\r\n
-----------------------------320761477111544\r\n
Content-Disposition: form-data; name="foobar_manager_record_domain-4-INITIAL_FORMS"\r\n
\r\n
0\r\n
---------------------\r\n
-----------------------------320761477111544\r\n
Content-Disposition: form-data; name="foobar_manager_record_domain-5-TOTAL_FORMS"\r\n
\r\n
0\r\n
-----------------------------320761477111544\r\n
Content-Disposition: form-data; name="foobar_manager_record_domain-5-INITIAL_FORMS"\r\n
\r\n
0\r\n
---------------------\r\n
-----------------------------320761477111544\r\n
Content-Disposition: form-data; name="foobar_manager_record_domain-6-TOTAL_FORMS"\r\n
\r\n
0\r\n
-----------------------------320761477111544\r\n
Content-Disposition: form-data; name="foobar_manager_record_domain-6-INITIAL_FORMS"\r\n
\r\n
0\r\n
---------------------\r\n
-----------------------------320761477111544\r\n
Content-Disposition: form-data; name="foobar_manager_record_domain-7-TOTAL_FORMS"\r\n
\r\n
0\r\n
-----------------------------320761477111544\r\n
Content-Disposition: form-data; name="foobar_manager_record_domain-7-INITIAL_FORMS"\r\n
\r\n
0\r\n
---------------------\r\n
-----------------------------320761477111544\r\n
Content-Disposition: form-data; name="foobar_manager_record_domain-8-TOTAL_FORMS"\r\n
\r\n
0\r\n
-----------------------------320761477111544\r\n
Content-Disposition: form-data; name="foobar_manager_record_domain-8-INITIAL_FORMS"\r\n
\r\n
0\r\n
---------------------\r\n""".decode('latin1').replace('\n', '').replace('\r', '\r\n'),
}
