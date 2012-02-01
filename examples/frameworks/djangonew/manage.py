#!/usr/bin/env python
import os, sys

"""
This example application demonstrates a project layout based on
Django 1.4 development.

For older releases of Django also see the djangotest example app.
"""

if __name__ == "__main__":
    from django.core.management import execute_from_command_line

    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "djangotest.settings")
    execute_from_command_line(sys.argv)
