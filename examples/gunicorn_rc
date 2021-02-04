#!/bin/sh

GUNICORN=/usr/local/bin/gunicorn
ROOT=/path/to/project
PID=/var/run/gunicorn.pid

APP=main:application

if [ -f $PID ]; then rm $PID; fi

cd $ROOT
exec $GUNICORN -c $ROOT/gunicorn.conf.py --pid=$PID $APP
