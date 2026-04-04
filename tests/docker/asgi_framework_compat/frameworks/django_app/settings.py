"""
Django settings for ASGI compatibility testing.
"""

import os

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# SECURITY WARNING: keep the secret key used in production secret!
SECRET_KEY = "django-insecure-test-key-for-asgi-compat"

# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = True

ALLOWED_HOSTS = ["*"]

# Application definition
INSTALLED_APPS = [
    "django.contrib.contenttypes",
    "django.contrib.auth",
    "channels",
]

MIDDLEWARE = []

ROOT_URLCONF = "urls"

TEMPLATES = []

# ASGI application
ASGI_APPLICATION = "asgi.application"

# Channel layers - use in-memory for testing
CHANNEL_LAYERS = {
    "default": {
        "BACKEND": "channels.layers.InMemoryChannelLayer"
    }
}

# Database - not needed for testing
DATABASES = {}

# Default primary key field type
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# Disable CSRF for testing
CSRF_TRUSTED_ORIGINS = ["http://localhost:*", "http://127.0.0.1:*"]
