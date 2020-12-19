#!/bin/bash

pip3 install gunicorn

if [ -n "$REQUIRENMENTS_FILE_PATH" ]; then
  pip install -r "$REQUIRENMENTS_FILE_PATH"
fi

if [ -n "$CONFIG_FILE_PATH" ]; then
  gunicorn -c $CONFIG_FILE_PATH $START_OPTION
fi

gunicorn $START_OPTION


