import re
from dataclasses import dataclass
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[3]
SOURCE_ROOTS = ("code", "compare_code", "configs/ch3")
CH3_DOCUMENTS = (
    "plan/experiment-protocol.md",
    "plan/implementation-plan.md",
    "plan/stage-gates.md",
    "plan/review/method-experiment-traceability.md",
    "tables/table-schema.md",
    "figures/data-manifest.md",
    "plan/task-packets/ch3-p00-t01.md",
    "plan/task-packets/ch3-p00-t02.md",
    "plan/task-packets/ch3-p00-t03.md",
    "plan/task-packets/ch3-p00-t04.md",
    "plan/task-packets/ch3-p01-t01.md",
    "plan/task-packets/ch3-p01-t02.md",
    "plan/task-packets/ch3-p01-t03.md",
)
SCANNED_SUFFIXES = {".py", ".md", ".yaml", ".yml", ".json", ".sh"}
MACHINE_OR_REMOTE = re.compile(
    r"/(?:root|Users)/|https?://|\b(?:ssh|scp)\s|\broot@|\b(?:\d{1,3}\.){3}\d{1,3}\b"
)
MARKDOWN_LINK = re.compile(r"\]\(([^)]+)\)")


@dataclass(frozen=True)
class LegacyException:
    reason: str
    cleanup_phase: str


def _legacy(
    path: str,
    line: int,
    text: str,
    reason: str,
    cleanup_phase: str,
) -> tuple[tuple[str, int, str], LegacyException]:
    return (path, line, text), LegacyException(reason, cleanup_phase)


LEGACY_ALLOWLIST: dict[tuple[str, int, str], LegacyException] = dict(
    [
        _legacy(
            "code/evaluate_risk_calibration.py",
            471,
            'parser.add_argument("--data-root", default="/root/autodl-tmp/dataset")',
            "Pre-CH3 calibration CLI default.",
            "CH3-P05",
        ),
        _legacy(
            "code/run_experiment.py",
            38,
            'data_root: str = "/root/autodl-tmp/dataset"',
            "Pre-CH3 runner default.",
            "CH3-P05",
        ),
        _legacy(
            "code/run_experiment.py",
            39,
            'output_dir: str = "/root/autodl-tmp/result"',
            "Pre-CH3 runner default.",
            "CH3-P05",
        ),
        _legacy(
            "code/run_experiment.py",
            881,
            'parser.add_argument("--data-root", default="/root/autodl-tmp/dataset")',
            "Pre-CH3 runner default.",
            "CH3-P05",
        ),
        _legacy(
            "code/run_experiment.py",
            882,
            'parser.add_argument("--output-dir", default="/root/autodl-tmp/result")',
            "Pre-CH3 runner default.",
            "CH3-P05",
        ),
        _legacy(
            "code/tests/test_cmapss_data.py",
            14,
            'DATA_ROOT = Path(os.environ.get("KST_DATA_ROOT", "/root/autodl-tmp/dataset"))',
            "Pre-CH3 dataset test default.",
            "CH3-P05",
        ),
        _legacy(
            "code/tests/test_experiment_framework.py",
            23,
            'DATA_ROOT = Path(os.environ.get("KST_DATA_ROOT", "/root/autodl-tmp/dataset"))',
            "Pre-CH3 framework test default.",
            "CH3-P05",
        ),
        _legacy(
            "code/tests/test_metropt_data.py",
            19,
            'DATA_ROOT = Path(os.environ.get("KST_DATA_ROOT", "/root/autodl-tmp/dataset"))',
            "Pre-CH3 dataset test default.",
            "CH3-P05",
        ),
        _legacy(
            "code/tests/test_model_components.py",
            7,
            'DATA_ROOT = Path(os.environ.get("KST_DATA_ROOT", "/root/autodl-tmp/dataset"))',
            "Pre-CH3 component test default.",
            "CH3-P05",
        ),
        _legacy(
            "code/tests/test_tep_data.py",
            18,
            'DATA_ROOT = Path(os.environ.get("KST_DATA_ROOT", "/root/autodl-tmp/dataset"))',
            "Pre-CH3 dataset test default.",
            "CH3-P05",
        ),
        _legacy(
            "code/train_cmapss_kaf_profiti.py",
            29,
            'parser.add_argument("--output-dir", default="/root/autodl-tmp/result")',
            "Pre-CH3 standalone trainer default.",
            "CH3-P05",
        ),
        _legacy(
            "code/train_metropt_kaf_profiti.py",
            31,
            'parser.add_argument("--output-dir", default="/root/autodl-tmp/result")',
            "Pre-CH3 standalone trainer default.",
            "CH3-P05",
        ),
        _legacy(
            "compare_code/TCN-Gaussian/README.md",
            12,
            "- Code: `https://github.com/locuslab/TCN`",
            "Legacy baseline source link.",
            "CH3-P06",
        ),
        _legacy(
            "compare_code/TCN-Gaussian/README.md",
            13,
            "- Paper: `https://arxiv.org/abs/1803.01271`",
            "Legacy baseline source link.",
            "CH3-P06",
        ),
        _legacy(
            "compare_code/TCN-Gaussian/README.md",
            48,
            "TMPDIR=/tmp /root/anaconda3/bin/conda run -n torch23 python -m pytest \\",
            "Legacy baseline test command.",
            "CH3-P06",
        ),
        _legacy(
            "compare_code/TCN-Gaussian/README.md",
            56,
            "TMPDIR=/tmp CUDA_VISIBLE_DEVICES=0 /root/anaconda3/bin/conda run -n torch23 python -u \\",
            "Legacy baseline training command.",
            "CH3-P06",
        ),
        _legacy(
            "compare_code/TCN-Gaussian/README.md",
            86,
            "TMPDIR=/tmp CUDA_VISIBLE_DEVICES=0 /root/anaconda3/bin/conda run -n torch23 python -u \\",
            "Legacy baseline training command.",
            "CH3-P06",
        ),
        _legacy(
            "compare_code/TCN-Gaussian/README.md",
            115,
            "TMPDIR=/tmp CUDA_VISIBLE_DEVICES=0 /root/anaconda3/bin/conda run -n torch23 python -u \\",
            "Legacy baseline training command.",
            "CH3-P06",
        ),
        _legacy(
            "compare_code/TCN-Gaussian/SOURCES.md",
            10,
            "- Official repository: https://github.com/locuslab/TCN",
            "Legacy baseline source link.",
            "CH3-P06",
        ),
        _legacy(
            "compare_code/TCN-Gaussian/SOURCES.md",
            11,
            "- Paper: https://arxiv.org/abs/1803.01271",
            "Legacy baseline source link.",
            "CH3-P06",
        ),
        _legacy(
            "compare_code/probabilistic_baselines/README.md",
            70,
            "TMPDIR=/tmp /root/anaconda3/envs/torch23/bin/python -m pytest \\",
            "Legacy baseline test command.",
            "CH3-P06",
        ),
        _legacy(
            "compare_code/probabilistic_baselines/README.md",
            81,
            "TMPDIR=/tmp CUDA_VISIBLE_DEVICES=0 /root/anaconda3/envs/torch23/bin/python -u \\",
            "Legacy baseline training command.",
            "CH3-P06",
        ),
        _legacy(
            "compare_code/probabilistic_baselines/README.md",
            115,
            "TMPDIR=/tmp CUDA_VISIBLE_DEVICES=0 /root/anaconda3/envs/torch23/bin/python -u \\",
            "Legacy baseline training command.",
            "CH3-P06",
        ),
        _legacy(
            "compare_code/probabilistic_baselines/README.md",
            143,
            "TMPDIR=/tmp CUDA_VISIBLE_DEVICES=0 /root/anaconda3/envs/torch23/bin/python -u \\",
            "Legacy baseline training command.",
            "CH3-P06",
        ),
        _legacy(
            "compare_code/probabilistic_baselines/SOURCES.md",
            11,
            "- Official repository: https://github.com/yuqinie98/PatchTST",
            "Legacy baseline source link.",
            "CH3-P06",
        ),
        _legacy(
            "compare_code/probabilistic_baselines/SOURCES.md",
            12,
            "- Paper: https://arxiv.org/abs/2211.14730",
            "Legacy baseline source link.",
            "CH3-P06",
        ),
        _legacy(
            "compare_code/probabilistic_baselines/SOURCES.md",
            18,
            "- Reference repository: https://github.com/YuliaRubanova/latent_ode",
            "Legacy baseline source link.",
            "CH3-P06",
        ),
        _legacy(
            "compare_code/probabilistic_baselines/SOURCES.md",
            19,
            "- Paper: https://arxiv.org/abs/1907.03907",
            "Legacy baseline source link.",
            "CH3-P06",
        ),
        _legacy(
            "compare_code/probabilistic_baselines/SOURCES.md",
            26,
            "- Official repository: https://github.com/usail-hkust/t-PatchGNN",
            "Legacy baseline source link.",
            "CH3-P06",
        ),
        _legacy(
            "compare_code/probabilistic_baselines/SOURCES.md",
            27,
            "- Paper page: https://openreview.net/forum?id=UZlMXUGI6e",
            "Legacy baseline source link.",
            "CH3-P06",
        ),
        _legacy(
            "compare_code/probabilistic_baselines/SOURCES.md",
            33,
            "- Official repository: https://github.com/yalavarthivk/ProFITi",
            "Legacy baseline source link.",
            "CH3-P06",
        ),
        _legacy(
            "compare_code/probabilistic_baselines/SOURCES.md",
            34,
            "- Paper: https://arxiv.org/abs/2402.06293",
            "Legacy baseline source link.",
            "CH3-P06",
        ),
        _legacy(
            "compare_code/probabilistic_baselines/SOURCES.md",
            41,
            "- Official repository: https://github.com/zhouziyu02/KAFNet",
            "Legacy baseline source link.",
            "CH3-P06",
        ),
        _legacy(
            "compare_code/probabilistic_baselines/SOURCES.md",
            42,
            "- Paper: https://arxiv.org/abs/2508.01971",
            "Legacy baseline source link.",
            "CH3-P06",
        ),
    ]
)


def _source_files() -> list[Path]:
    files = []
    for root in SOURCE_ROOTS:
        files.extend(
            path
            for path in (PROJECT_ROOT / root).rglob("*")
            if (
                path.is_file()
                and path.suffix in SCANNED_SUFFIXES
                and path != Path(__file__).resolve()
                and ".pytest_cache" not in path.parts
                and "__pycache__" not in path.parts
            )
        )
    return sorted(files)


def _machine_findings() -> set[tuple[str, int, str]]:
    findings = set()
    for path in _source_files():
        relative_path = path.relative_to(PROJECT_ROOT).as_posix()
        for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if MACHINE_OR_REMOTE.search(line):
                findings.add((relative_path, line_number, line.strip()))
    return findings


def _chapter_three_prose(path: Path) -> str:
    content = path.read_text(encoding="utf-8")
    if path.as_posix().endswith("plan/implementation-plan.md"):
        content = content[content.index("## 11.") :]
    content = re.sub(r"```.*?```", "", content, flags=re.DOTALL)
    return re.sub(r"`[^`]*`", "", content)


def test_machine_and_remote_references_are_explicitly_allowlisted():
    findings = _machine_findings()
    unexpected = findings - set(LEGACY_ALLOWLIST)
    stale = set(LEGACY_ALLOWLIST) - findings

    assert not unexpected, "Unexpected portability finding(s):\n" + "\n".join(
        ":".join((path, str(line), text)) for path, line, text in sorted(unexpected)
    )
    assert not stale, "Stale portability allowlist entry or changed legacy line(s):\n" + "\n".join(
        ":".join((path, str(line), text)) for path, line, text in sorted(stale)
    )
    assert all(
        exception.reason and exception.cleanup_phase.startswith("CH3-P")
        for exception in LEGACY_ALLOWLIST.values()
    )
    assert all(
        not path.startswith(
            (
                "configs/ch3/",
                "code/kaf_profiti/experiments/ch3/",
                "code/tests/ch3/",
            )
        )
        for path, _, _ in LEGACY_ALLOWLIST
    )


def test_chapter_three_documents_have_no_machine_references_or_absolute_internal_links():
    violations = []
    for relative_path in CH3_DOCUMENTS:
        path = PROJECT_ROOT / relative_path
        prose = _chapter_three_prose(path)
        for line_number, line in enumerate(prose.splitlines(), start=1):
            if MACHINE_OR_REMOTE.search(line):
                violations.append(f"{relative_path}:{line_number}: machine or remote reference")
        for target in MARKDOWN_LINK.findall(prose):
            target_path = target.split("#", maxsplit=1)[0]
            if target_path.startswith(("/", "file:")):
                violations.append(f"{relative_path}: absolute internal link: {target}")
    assert not violations, "\n".join(violations)
