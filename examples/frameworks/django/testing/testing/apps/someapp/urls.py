from django.conf.urls.defaults import patterns, url

urlpatterns = patterns('',
    url(r'^acsv$', 'testing.apps.someapp.views.acsv'),
    url(r'^$', 'testing.apps.someapp.views.home'),

)
