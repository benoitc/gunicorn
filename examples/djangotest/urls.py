from django.conf.urls.defaults import *

urlpatterns = patterns('',
    url(r'^$', 'djangotest.testing.views.home'),
)

