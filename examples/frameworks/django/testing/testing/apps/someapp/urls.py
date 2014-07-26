from django.conf.urls import patterns, include, url

urlpatterns = patterns('',
    url(r'^acsv$', 'testing.apps.someapp.views.acsv'),
    url(r'^$', 'testing.apps.someapp.views.home'),

)
