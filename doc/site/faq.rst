template: doc.html
title: FAQ

FAQ
===

How to reload my application in Gunicorn ?
  You can gracefully reload by sending HUP signal to gunicorn::

    $ kill -HUP masterpid

How to increase/decrease number of running workers ?
  send TTIN/TTOUT signals to do it::

    $ kill -TTIN masterpid
  
  will increase the number from one worker
  
How to set SCRIPT_NAME ?
  By default SCRIPT_name is an empy string. Value could be changed by passing
  `SCRIPT_NAME` in environment (apache way) or as an HTTP header (nginx way).

