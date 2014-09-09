from django.conf.urls import url

from . import views

urlpatterns = [
    url(r'^acsv$', views.acsv),
    url(r'^$', views.home),
]
