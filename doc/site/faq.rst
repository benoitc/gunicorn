template: doc.html

FAQ
===

How to reload my application in Gunicorn ?
  You can gracefully reload by sending HUP signal to gunicorn::

    $ kill -HUP masterpid

How to increase/decrease number of running workers ?
  send TTIN/TTOUT signals to do it::

    $ kill -TTIN masterpid
  
  will increase the number from one worker

