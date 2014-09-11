# Create your views here.

import csv
import io
import os
from django import forms
from django.http import HttpResponse
from django.shortcuts import render_to_response
from django.template import RequestContext
import tempfile

class MsgForm(forms.Form):
    subject = forms.CharField(max_length=100)
    message = forms.CharField()
    f = forms.FileField()


def home(request):
    from django.conf import settings
    print(settings.SOME_VALUE)
    subject = None
    message = None
    size = 0
    print(request.META)
    if request.POST:
        form = MsgForm(request.POST, request.FILES)
        print(request.FILES)
        if form.is_valid():
            subject = form.cleaned_data['subject']
            message = form.cleaned_data['message']
            f = request.FILES['f']

            if not hasattr(f, "fileno"):
                size = len(f.read())
            else:
                try:
                    size = int(os.fstat(f.fileno())[6])
                except io.UnsupportedOperation:
                    size = len(f.read())
    else:
        form = MsgForm()

    return render_to_response('home.html', {
        'form': form,
        'subject': subject,
        'message': message,
        'size': size
    }, RequestContext(request))


def acsv(request):
    rows = [
        {'a': 1, 'b': 2},
        {'a': 3, 'b': 3}
    ]

    response = HttpResponse(mimetype='text/csv')
    response['Content-Disposition'] = 'attachment; filename=report.csv'

    writer = csv.writer(response)
    writer.writerow(['a', 'b'])

    for r in rows:
        writer.writerow([r['a'], r['b']])

    return response
