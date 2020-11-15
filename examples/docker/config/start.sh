#!/bin/bash

pip3 install gunicorn &&\
if [ -n "$REQUIRENMENTS_FILE_PATH" ]; then
  pip install -r "$REQUIRENMENTS_FILE_PATH"
fi &&\
if [ -n "$CONFIG_FILE_PATH" ]; then
  gunicorn -c `echo -e "$CONFIG_FILE_PATH"` `echo -e "$START_OPTION"`
fi &&\
gunicorn `echo -e "$START_OPTION"`
