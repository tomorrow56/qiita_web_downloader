import os
import sys

# Ensure project root is on sys.path so `src` can be imported
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(CURRENT_DIR)
if PROJECT_ROOT not in sys.path:
  sys.path.insert(0, PROJECT_ROOT)

# Export Flask WSGI app for Vercel
from src.main import app  # noqa: F401
