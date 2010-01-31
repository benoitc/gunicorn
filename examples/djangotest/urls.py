
from django.conf.urls.defaults import patterns,include

urlpatterns = patterns('',
    ('^$', include("testing.urls")),
)