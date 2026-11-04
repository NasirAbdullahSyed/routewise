"""Expose the Django application as a Vercel Python function."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from config.wsgi import application

app = application
