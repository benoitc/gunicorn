from django.conf.urls.defaults import patterns, url, handler404, handler500

urlpatterns = patterns('',
    url(r'^$', 'djangotest.testing.views.home'),
)

def __exported_functionality__():
    return [handler404, handler500]