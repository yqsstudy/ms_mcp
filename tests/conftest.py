"""Pytest configuration for the test suite."""

import sys
import os

# Ensure the project root is in sys.path
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

# Remove .conda from sys.path if present to avoid conflicts
sys.path = [p for p in sys.path if '.conda' not in p]
