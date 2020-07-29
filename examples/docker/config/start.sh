#!/bin/bash

bash /config/config.sh &&\
bash /config/install.sh &&\
gunicorn -c `echo -e "$CONFIG_FILE_PATH"` `echo -e "$START_OPTION"`