"""CH34-S00-T02: diagnostics-script portability guard.

The FD004 diagnostic scripts must be runnable on the local machine and on
AutoDL without editing source: no machine-specific home directory, no fixed
data/result root, and no remote address may be hardcoded. Paths must come from
CLI arguments / KST_* environment variables / repository-relative defaults.
"""

import re
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]
_DIAG_DIR = _REPO_ROOT / "code" / "diagnostics"

# Same machine/remote pattern as code/tests/ch3/test_portability_policy.py.
_MACHINE_OR_REMOTE = re.compile(
    r"/(?:root|Users)/|https?://|\b(?:ssh|scp)\s|\broot@|\b(?:\d{1,3}\.){3}\d{1,3}\b"
)

# A Path("/...") absolute literal assigned to a data/result/runs constant.
_ABSOLUTE_PATH_LITERAL = re.compile(
    r"^([A-Z_]+)\s*=\s*Path\(\s*[\"']/", re.MULTILINE
)


def _diagnostic_files():
    return sorted(_DIAG_DIR.glob("*.py"))


def _machine_findings():
    findings = {}
    for path in _diagnostic_files():
        for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if _MACHINE_OR_REMOTE.search(line):
                findings.setdefault(path.name, []).append((line_no, line.strip()))
    return findings


def _absolute_literal_findings():
    findings = {}
    for path in _diagnostic_files():
        for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if _ABSOLUTE_PATH_LITERAL.search(line):
                findings.setdefault(path.name, []).append((line_no, line.strip()))
    return findings


def test_diagnostic_scripts_have_no_machine_or_remote_references():
    findings = _machine_findings()
    assert not findings, f"machine/remote references in diagnostics:\n{findings}"


def test_diagnostic_scripts_do_not_hardcode_absolute_data_or_result_paths():
    findings = _absolute_literal_findings()
    assert not findings, f"absolute Path literals in diagnostics:\n{findings}"


def test_diagnostic_scripts_resolve_paths_at_runtime():
    # Every diagnostics script must wire path resolution through CLI/env vars
    # rather than module-level hardcoded roots.
    for path in _diagnostic_files():
        text = path.read_text(encoding="utf-8")
        assert "resolve_runtime_paths" in text, (
            f"{path.name} must resolve paths via resolve_runtime_paths"
        )
