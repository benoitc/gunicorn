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
    "body": b"""-----------------------------320761477111544
Content-Disposition: form-data; name="csrfmiddlewaretoken"

XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX
-----------------------------320761477111544
Content-Disposition: form-data; name="_save"

Save
-----------------------------320761477111544
Content-Disposition: form-data; name="name"

test.example.org
-----------------------------320761477111544
Content-Disposition: form-data; name="type"

NATIVE
-----------------------------320761477111544
Content-Disposition: form-data; name="master"


-----------------------------320761477111544
Content-Disposition: form-data; name="foobar_manager_dynamiczone_domain-TOTAL_FORMS"

1
-----------------------------320761477111544
Content-Disposition: form-data; name="foobar_manager_dynamiczone_domain-INITIAL_FORMS"

1
-----------------------------320761477111544
Content-Disposition: form-data; name="foobar_manager_dynamiczone_domain-MAX_NUM_FORMS"

1
-----------------------------320761477111544
Content-Disposition: form-data; name="foobar_manager_dynamiczone_domain-0-is_dynamic"

on
-----------------------------320761477111544
Content-Disposition: form-data; name="foobar_manager_dynamiczone_domain-0-id"

1
-----------------------------320761477111544
Content-Disposition: form-data; name="foobar_manager_dynamiczone_domain-0-domain"

2
-----------------------------320761477111544
Content-Disposition: form-data; name="foobar_manager_dynamiczone_domain-__prefix__-id"


-----------------------------320761477111544
Content-Disposition: form-data; name="foobar_manager_dynamiczone_domain-__prefix__-domain"

2
-----------------------------320761477111544
Content-Disposition: form-data; name="foobar_manager_record_domain-TOTAL_FORMS"

1
-----------------------------320761477111544
Content-Disposition: form-data; name="foobar_manager_record_domain-INITIAL_FORMS"

1
-----------------------------320761477111544
Content-Disposition: form-data; name="foobar_manager_record_domain-MAX_NUM_FORMS"

1
-----------------------------320761477111544
Content-Disposition: form-data; name="foobar_manager_record_domain-0-ttl"

3600
-----------------------------320761477111544
Content-Disposition: form-data; name="foobar_manager_record_domain-0-primary"

ns.example.org
-----------------------------320761477111544
Content-Disposition: form-data; name="foobar_manager_record_domain-0-hostmaster"

hostmaster.test.example.org
-----------------------------320761477111544
Content-Disposition: form-data; name="foobar_manager_record_domain-0-serial"

2013121701
-----------------------------320761477111544
Content-Disposition: form-data; name="foobar_manager_record_domain-0-refresh"

10800
-----------------------------320761477111544
Content-Disposition: form-data; name="foobar_manager_record_domain-0-retry"

3600
-----------------------------320761477111544
Content-Disposition: form-data; name="foobar_manager_record_domain-0-expire"

604800
-----------------------------320761477111544
Content-Disposition: form-data; name="foobar_manager_record_domain-0-default_ttl"

3600
-----------------------------320761477111544
Content-Disposition: form-data; name="foobar_manager_record_domain-0-id"

16
-----------------------------320761477111544
Content-Disposition: form-data; name="foobar_manager_record_domain-0-domain"

2
-----------------------------320761477111544
Content-Disposition: form-data; name="foobar_manager_record_domain-__prefix__-ttl"


-----------------------------320761477111544
Content-Disposition: form-data; name="foobar_manager_record_domain-__prefix__-primary"


-----------------------------320761477111544
Content-Disposition: form-data; name="foobar_manager_record_domain-__prefix__-hostmaster"


-----------------------------320761477111544
Content-Disposition: form-data; name="foobar_manager_record_domain-__prefix__-serial"

1
-----------------------------320761477111544
Content-Disposition: form-data; name="foobar_manager_record_domain-__prefix__-refresh"

10800
-----------------------------320761477111544
Content-Disposition: form-data; name="foobar_manager_record_domain-__prefix__-retry"

3600
-----------------------------320761477111544
Content-Disposition: form-data; name="foobar_manager_record_domain-__prefix__-expire"

604800
-----------------------------320761477111544
Content-Disposition: form-data; name="foobar_manager_record_domain-__prefix__-default_ttl"

3600
-----------------------------320761477111544
Content-Disposition: form-data; name="foobar_manager_record_domain-__prefix__-id"


-----------------------------320761477111544
Content-Disposition: form-data; name="foobar_manager_record_domain-__prefix__-domain"

2
-----------------------------320761477111544
Content-Disposition: form-data; name="foobar_manager_record_domain-2-TOTAL_FORMS"

0
-----------------------------320761477111544
Content-Disposition: form-data; name="foobar_manager_record_domain-2-INITIAL_FORMS"

0
-----------------------------320761477111544
Content-Disposition: form-data; name="foobar_manager_record_domain-2-MAX_NUM_FORMS"

1000
-----------------------------320761477111544
Content-Disposition: form-data; name="foobar_manager_record_domain-2-__prefix__-id"


-----------------------------320761477111544
Content-Disposition: form-data; name="foobar_manager_record_domain-2-__prefix__-domain"

2
-----------------------------320761477111544
Content-Disposition: form-data; name="foobar_manager_record_domain-2-__prefix__-name"


-----------------------------320761477111544
Content-Disposition: form-data; name="foobar_manager_record_domain-2-__prefix__-ttl"


-----------------------------320761477111544
Content-Disposition: form-data; name="foobar_manager_record_domain-2-__prefix__-content"


-----------------------------320761477111544
Content-Disposition: form-data; name="foobar_manager_record_domain-3-TOTAL_FORMS"

0
-----------------------------320761477111544
Content-Disposition: form-data; name="foobar_manager_record_domain-3-INITIAL_FORMS"

0
-----------------------------320761477111544
Content-Disposition: form-data; name="foobar_manager_record_domain-3-MAX_NUM_FORMS"

1000
-----------------------------320761477111544
Content-Disposition: form-data; name="foobar_manager_record_domain-3-__prefix__-id"


-----------------------------320761477111544
Content-Disposition: form-data; name="foobar_manager_record_domain-3-__prefix__-domain"

2
-----------------------------320761477111544
Content-Disposition: form-data; name="foobar_manager_record_domain-3-__prefix__-name"


-----------------------------320761477111544
Content-Disposition: form-data; name="foobar_manager_record_domain-3-__prefix__-ttl"


-----------------------------320761477111544
Content-Disposition: form-data; name="foobar_manager_record_domain-3-__prefix__-prio"


-----------------------------320761477111544
Content-Disposition: form-data; name="foobar_manager_record_domain-3-__prefix__-content"


-----------------------------320761477111544
Content-Disposition: form-data; name="foobar_manager_record_domain-4-TOTAL_FORMS"

0
-----------------------------320761477111544
Content-Disposition: form-data; name="foobar_manager_record_domain-4-INITIAL_FORMS"

0
---------------------
-----------------------------320761477111544
Content-Disposition: form-data; name="foobar_manager_record_domain-5-TOTAL_FORMS"

0
-----------------------------320761477111544
Content-Disposition: form-data; name="foobar_manager_record_domain-5-INITIAL_FORMS"

0
---------------------
-----------------------------320761477111544
Content-Disposition: form-data; name="foobar_manager_record_domain-6-TOTAL_FORMS"

0
-----------------------------320761477111544
Content-Disposition: form-data; name="foobar_manager_record_domain-6-INITIAL_FORMS"

0
---------------------
-----------------------------320761477111544
Content-Disposition: form-data; name="foobar_manager_record_domain-7-TOTAL_FORMS"

0
-----------------------------320761477111544
Content-Disposition: form-data; name="foobar_manager_record_domain-7-INITIAL_FORMS"

0
---------------------
-----------------------------320761477111544
Content-Disposition: form-data; name="foobar_manager_record_domain-8-TOTAL_FORMS"

0
-----------------------------320761477111544
Content-Disposition: form-data; name="foobar_manager_record_domain-8-INITIAL_FORMS"

0
---------------------
""".decode('utf-8').replace('\n', '\r\n').encode('utf-8'),
}
