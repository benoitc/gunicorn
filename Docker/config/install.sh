#!/bin/bash

if [ IS_ASYNC == true ]; then
  pip3 gunicorn install greenlet, eventlet>=0.25.2 , gunicorn[eventlet] greenlet, gevent>=1.4, gunicorn[gevent]
fi

if [ IS_ASTNC == false ]; then
  pip3 gunicorn install tornado gunicorn[tornado]
fi

