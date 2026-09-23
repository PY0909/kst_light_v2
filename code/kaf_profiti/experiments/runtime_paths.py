"""Portable runtime paths for Chapter 3 experiment entry points."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Mapping


@dataclass(frozen=True)
class RuntimePaths:
    """Normalized roots consumed by an experiment run."""

    project_root: Path
    data_root: Path
    output_root: Path


def _repository_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _resolve_against_project(value: str, project_root: Path) -> Path:
    candidate = Path(value).expanduser()
    if not candidate.is_absolute():
        candidate = project_root / candidate
    return candidate.resolve()


def _configured_value(
    explicit_value: str | None,
    environ: Mapping[str, str],
    key: str,
) -> str | None:
    if explicit_value:
        return explicit_value
    environment_value = environ.get(key)
    return environment_value or None


def resolve_runtime_paths(
    data_root: str | None,
    output_root: str | None,
    environ: Mapping[str, str],
    *,
    require_existing_data: bool = False,
) -> RuntimePaths:
    """Resolve CLI, environment, and repository-relative experiment roots.

    Explicit ``data_root`` and ``output_root`` values override their corresponding
    environment variables. ``KST_DATA_ROOT`` and ``KST_RESULT_ROOT`` then override
    the ``dataset`` and ``result`` defaults below ``KST_PROJECT_ROOT`` (or this
    repository's inferred root). Relative paths are always resolved from the
    selected project root, never from the caller's working directory.

    Set ``require_existing_data`` for formal runs to reject a missing data root.
    Output directories are intentionally not created by this resolver.
    """

    inferred_root = _repository_root()
    project_root_value = environ.get("KST_PROJECT_ROOT")
    project_root = (
        _resolve_against_project(project_root_value, inferred_root)
        if project_root_value
        else inferred_root
    )

    selected_data_root = _configured_value(data_root, environ, "KST_DATA_ROOT")
    selected_output_root = _configured_value(output_root, environ, "KST_RESULT_ROOT")
    resolved_data_root = _resolve_against_project(selected_data_root or "dataset", project_root)
    resolved_output_root = _resolve_against_project(selected_output_root or "result", project_root)

    if require_existing_data and not resolved_data_root.is_dir():
        raise FileNotFoundError(f"Configured data root does not exist: {resolved_data_root}")

    return RuntimePaths(
        project_root=project_root,
        data_root=resolved_data_root,
        output_root=resolved_output_root,
    )
