from django.conf.urls.defaults import patterns, url

urlpatterns = patterns('',
    url(r'^acsv$', 'testing.views.acsv'),
    url(r'^$', 'testing.views.home'),
    
)
