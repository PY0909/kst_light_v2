import importlib.util
import sys
from pathlib import Path

import pytest


def _load_runtime_paths_module():
    module_path = (
        Path(__file__).resolve().parents[2]
        / "kaf_profiti"
        / "experiments"
        / "runtime_paths.py"
    )
    spec = importlib.util.spec_from_file_location("ch3_runtime_paths_under_test", module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load runtime paths module: {module_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


resolve_runtime_paths = _load_runtime_paths_module().resolve_runtime_paths


def test_explicit_roots_override_environment_roots(tmp_path: Path):
    project_root = tmp_path / "project"
    project_root.mkdir()
    environ = {
        "KST_PROJECT_ROOT": str(project_root),
        "KST_DATA_ROOT": str(project_root / "environment-data"),
        "KST_RESULT_ROOT": str(project_root / "environment-result"),
    }

    paths = resolve_runtime_paths(
        "cli-data/../cli-data",
        "cli-result/../cli-result",
        environ,
    )

    assert paths.project_root == project_root.resolve()
    assert paths.data_root == (project_root / "cli-data").resolve()
    assert paths.output_root == (project_root / "cli-result").resolve()


def test_environment_roots_override_repository_relative_defaults(tmp_path: Path):
    project_root = tmp_path / "project"
    project_root.mkdir()
    environ = {
        "KST_PROJECT_ROOT": str(project_root),
        "KST_DATA_ROOT": "environment/../environment-data",
        "KST_RESULT_ROOT": "environment/../environment-result",
    }

    paths = resolve_runtime_paths(None, None, environ)

    assert paths.data_root == (project_root / "environment-data").resolve()
    assert paths.output_root == (project_root / "environment-result").resolve()


def test_repository_relative_defaults_and_paths_are_normalized(tmp_path: Path):
    project_root = tmp_path / "project"
    project_root.mkdir()

    paths = resolve_runtime_paths(None, None, {"KST_PROJECT_ROOT": str(project_root)})

    assert paths.project_root == project_root.resolve()
    assert paths.data_root == (project_root / "dataset").resolve()
    assert paths.output_root == (project_root / "results").resolve()
    assert all(path.is_absolute() for path in (paths.project_root, paths.data_root, paths.output_root))


def test_formal_mode_rejects_missing_data_root_with_clear_error(tmp_path: Path):
    project_root = tmp_path / "project"
    project_root.mkdir()

    with pytest.raises(FileNotFoundError, match="Configured data root does not exist"):
        resolve_runtime_paths(
            "missing-data",
            None,
            {"KST_PROJECT_ROOT": str(project_root)},
            require_existing_data=True,
        )


def test_formal_mode_accepts_an_existing_data_root(tmp_path: Path):
    project_root = tmp_path / "project"
    data_root = project_root / "dataset"
    data_root.mkdir(parents=True)

    paths = resolve_runtime_paths(
        None,
        None,
        {"KST_PROJECT_ROOT": str(project_root)},
        require_existing_data=True,
    )

    assert paths.data_root == data_root.resolve()
