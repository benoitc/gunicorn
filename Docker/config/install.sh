#! /bin/bash

if [ -n "$FRAMEWORK_VERSION" ] && [ -n "$FRAMEWORK" ]; then
  pip3 install "$FRAMEWORK"=="$FRAMEWORK_VERSION"
elif [ -n "$FRAMEWORK" ]; then
    pip3 install "$FRAMEWORK"
fi