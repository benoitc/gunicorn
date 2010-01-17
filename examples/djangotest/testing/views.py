# Create your views here.

from django import forms
from django.shortcuts import render_to_response

class MsgForm(forms.Form):
    subject = forms.CharField(max_length=100)
    message = forms.CharField()
    

def home(request):
    
    subject = None
    message = None
    if request.POST:
        form = MsgForm(request.POST)
        if form.is_valid():
            subject = form.cleaned_data['subject']
            message = form.cleaned_data['message']
    else:
        form = MsgForm()
        
        
    return render_to_response('home.html', {
        'form': form,
        'subject': subject,
        'message': message
    })
    
    
            