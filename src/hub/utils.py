"""Utility functions for the Hub.

NOTE: Common utilities are now in the shared module at project root.
This module re-exports them for backwards compatibility.
"""

import sys
from pathlib import Path

# Add shared module to path
_project_root = Path(__file__).parent.parent.parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

# Re-export from shared module for backwards compatibility
from shared.normalization import normalize_device_name  # noqa: E402

__all__ = ["normalize_device_name"]
