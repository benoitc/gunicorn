from django.conf.urls.defaults import include, url

urlpatterns = [
    url(r'^', include("testing.urls")),
]
