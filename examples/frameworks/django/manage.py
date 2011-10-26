#!/usr/bin/env python
import os, sys

if __name__ == "__main__":
    from django.conf import ENVIRONMENT_VARIABLE
    from django.core.management import execute_from_command_line

    os.environ.setdefault(ENVIRONMENT_VARIABLE, "testing.settings")
    execute_from_command_line(sys.argv)
