#!/bin/bash

if [ IS_ASYNC == true ]; then
  pip3 install greenlet, eventlet, gunicorn[eventlet] greenlet, gevent, gunicorn[gevent]
fi

if [ IS_ASTNC == false ]; then
  pip3 install gunicorn[tornado]
fi

