"""pytest conftest — automatically add code/ to sys.path and set KST_DATA_ROOT."""
import os
import sys
from pathlib import Path

# Ensure code/ is on sys.path so that `from kaf_profiti...` works
_CODE_DIR = Path(__file__).resolve().parent.parent
if str(_CODE_DIR) not in sys.path:
    sys.path.insert(0, str(_CODE_DIR))

# Portable default: repository-relative dataset dir; override with KST_DATA_ROOT
if "KST_DATA_ROOT" not in os.environ:
    os.environ["KST_DATA_ROOT"] = str(_CODE_DIR.parent / "dataset")
