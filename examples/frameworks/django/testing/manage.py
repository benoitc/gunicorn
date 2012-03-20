#!/usr/bin/env python
import os, sys

if __name__ == "__main__":
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "testing.settings")

    from django.core.management import execute_from_command_line

    execute_from_command_line(sys.argv)
