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

#: V2 handoff: data-dependent tests can skip cleanly when the dataset tree is
#: absent (e.g. code-only handoff copies). Checked once at collection.
DATA_AVAILABLE = os.path.isdir(os.environ["KST_DATA_ROOT"]) and any(
    entry in os.listdir(os.environ["KST_DATA_ROOT"])
    for entry in ("CMAPSSData", "metropt+3+dataset", "dataverse_files")
)
