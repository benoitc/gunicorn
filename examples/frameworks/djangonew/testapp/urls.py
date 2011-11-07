from django.conf.urls.defaults import patterns, url

urlpatterns = patterns('',
    url(r'^acsv$', 'testapp.views.acsv'),
    url(r'^$', 'testapp.views.home'),
    
)
