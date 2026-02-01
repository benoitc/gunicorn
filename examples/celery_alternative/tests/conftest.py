"""
Pytest configuration for Celery Replacement tests.
"""

import sys
from pathlib import Path

# Add gunicorn source to path for imports
gunicorn_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(gunicorn_root))
