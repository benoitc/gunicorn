#! /bin/bash

if [ -n "$REQUIRENMENTS_FILE_PATH" ]; then
  pip3 install -r "$REQUIRENMENTS_FILE_PATH"
fi
