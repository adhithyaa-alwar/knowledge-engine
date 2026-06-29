# conftest.py
#
# This file is automatically loaded by pytest before running tests.
# It adds the src/ folder to Python's path so tests can import from it.

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))
