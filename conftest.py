"""Make ``src`` importable for tests and example scripts without an install.

pytest also picks up ``pythonpath = ["src"]`` from pyproject; this is a
belt-and-suspenders fallback so ``python -m pytest`` works anywhere.
"""
import os
import sys

_SRC = os.path.join(os.path.dirname(__file__), "src")
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)
