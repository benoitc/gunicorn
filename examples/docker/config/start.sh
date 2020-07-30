#!/bin/bash

if [ -n "$CONFIG_FILE_PATH" ] && [ "$CONFIG_FILE_PATH" == "/config/config.py" ]; then
  bash /config/config.sh
fi &&\
bash /config/install.sh &&\
gunicorn -c `echo -e "$CONFIG_FILE_PATH"` `echo -e "$START_OPTION"`


