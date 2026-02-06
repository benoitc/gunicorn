#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.

from django.conf.urls import url

from . import views

urlpatterns = [
    url(r'^acsv$', views.acsv),
    url(r'^$', views.home),
]
