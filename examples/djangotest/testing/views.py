# Create your views here.

import os
from django import forms
from django.shortcuts import render_to_response
import tempfile

class MsgForm(forms.Form):
    subject = forms.CharField(max_length=100)
    message = forms.CharField()
    f = forms.FileField()
    

def home(request):
    
    subject = None
    message = None
    size = 0
    if request.POST:
        form = MsgForm(request.POST, request.FILES)
        print request.FILES
        if form.is_valid():
            subject = form.cleaned_data['subject']
            message = form.cleaned_data['message']
            f = request.FILES['f']
            tmp =  tempfile.TemporaryFile()
            for chunk in f.chunks():
                tmp.write(chunk)
            tmp.flush()
            size = int(os.fstat(tmp.fileno())[6])
    else:
        form = MsgForm()
        
        
    return render_to_response('home.html', {
        'form': form,
        'subject': subject,
        'message': message,
        'size': size
    })
    
    
            