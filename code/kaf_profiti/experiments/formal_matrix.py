"""Authoritative formal-matrix schema, hard gates, and dry-run expansion.

V2-ROADMAP C0 (V2-X0-CLOSE-T03) creates three authoritative configuration
entries and pins them with schema hard gates:

* ``configs/ch3/point_matrix.yaml``      exactly 5 point baselines + ``kst_light_v2``
* ``configs/ch4/probabilistic_matrix.yaml`` must use ``kst_flow_v2`` as ours
* ``configs/ch5/risk_matrix.yaml``       must declare ``kst_probflow_v2``
  (``status: planned`` is allowed at C0 for schema dry-run only)

Legacy pilot infrastructure under ``configs/pilot/`` is historical-audit-only;
the formal runner entry (``run_pilot_matrix.py --config``) accepts nothing but
the three authoritative paths. Protocol windows and condition sets follow the
A.1 data contract and are enforced, not assumed.
"""

import hashlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

import yaml

from kaf_profiti.experiments.registry import get_model_spec

#: Chapter -> repository-relative authoritative matrix entry (the only paths
#: the formal runner accepts).
AUTHORITATIVE_MATRICES: Dict[str, str] = {
    "ch3": "configs/ch3/point_matrix.yaml",
    "ch4": "configs/ch4/probabilistic_matrix.yaml",
    "ch5": "configs/ch5/risk_matrix.yaml",
}

#: Legacy own-model ids: historical audit only, never valid in formal matrices.
FORBIDDEN_MODEL_IDS = frozenset({"kst_light", "kst_probflow"})

#: Per-chapter model composition gates.
CHAPTER_GATES: Dict[str, Dict[str, object]] = {
    "ch3": {
        "track": "point",
        "baselines": frozenset({"li_tcn", "ff_gru", "masked_tcn", "gru_d", "ode_rnn"}),
        "baseline_count": 5,
        "ours": ("kst_light_v2",),
    },
    "ch4": {
        "track": "probabilistic",
        # KAFNet ids are structurally allowed (V2-CH4-CODE-T04 adapters) but the
        # registry gate below rejects them while they are not_implemented.
        "baselines": frozenset({
            "tcn_gaussian", "patchtst_gaussian", "gru_d_gaussian",
            "ode_rnn_gaussian", "grafiti_gaussian", "profiti",
            "kafnet", "kafnet_gaussian", "kaf_profiti_marginal", "kaf_profiti_joint",
        }),
        "baseline_count": 6,
        "ours": ("kst_flow_v2",),
    },
    "ch5": {
        "track": "risk",
        "baselines": frozenset({"tcn_gaussian", "patchtst_gaussian", "profiti",
                                "kaf_profiti_joint"}),
        "baseline_count": 4,
        "ours": ("kst_probflow_v2",),
    },
}

#: A.1 data contract: protocol id -> (history_len, pred_len, stride).
PROTOCOL_CONTRACT: Dict[str, tuple] = {
    "metropt3_chrono_502030_v2": (168, 24, 60),
    "cmapss_fd001": (50, 10, 1),
    "cmapss_fd002": (50, 10, 1),
    "cmapss_fd003": (50, 10, 1),
    "cmapss_fd004": (50, 10, 1),
    "tep_faulty": (96, 24, 12),
}

#: MetroPT carries the six-condition axis in ch3 only; ch4/ch5 pin the central
#: condition pair and leave the robustness axis to V2-POST.
METROPT_CH3_CONDITIONS = frozenset({
    ("mixed", 0.30), ("random", 0.00), ("random", 0.30),
    ("random", 0.70), ("low_rate", 0.30), ("block_offline", 0.30),
})
EXTERNAL_CONDITION = frozenset({("mixed", 0.30)})

_REQUIRED_RECIPE_FIELDS = (
    "epochs", "batch_size", "learning_rate", "weight_decay",
    "scheduler", "grad_clip_norm",
)
_REQUIRED_SEED_FIELDS = ("seed", "split_seed", "mask_seed")


@dataclass(frozen=True)
class FormalRunKey:
    """One expanded formal-matrix cell (protocol x condition x model x seed)."""

    protocol: str
    track: str
    model_id: str
    head_type: str
    condition_id: str
    seed: int
    family: str
    status: str

    @property
    def scientific_key(self) -> str:
        return f"{self.protocol}|{self.track}|{self.model_id}|{self.head_type}|{self.condition_id}|{self.seed}"


@dataclass(frozen=True)
class FormalMatrix:
    chapter: str
    track: str
    matrix_id: str
    recipe_version: str
    matrix_sha256: str
    path: str
    seeds: Dict[str, int]
    recipe: Dict[str, object]
    selection_metric: str
    models: List[Dict] = field(default_factory=list)
    protocols: Dict[str, Dict] = field(default_factory=dict)

    @property
    def planned_model_ids(self) -> List[str]:
        return [m["model_id"] for m in self.models if m.get("status") == "planned"]

    def expand(self) -> List[FormalRunKey]:
        keys: List[FormalRunKey] = []
        for protocol_id, protocol in self.protocols.items():
            for condition in protocol["conditions"]:
                for model in self.models:
                    keys.append(FormalRunKey(
                        protocol=protocol_id,
                        track=self.track,
                        model_id=model["model_id"],
                        head_type=model["head_type"],
                        condition_id=condition["condition_id"],
                        seed=int(self.seeds["seed"]),
                        family=model["family"],
                        status=str(model.get("status", "active")),
                    ))
        return keys


def expand_formal_matrix(matrix: FormalMatrix) -> List[FormalRunKey]:
    return matrix.expand()


def assert_no_planned_for_execution(matrix: FormalMatrix) -> None:
    """Planned models may appear in schema dry-run only, never in execution."""

    planned = matrix.planned_model_ids
    if planned:
        raise ValueError(
            f"matrix {matrix.matrix_id} declares planned models {planned}; "
            "planned entries support schema dry-run only and must be registered "
            "as enabled (e.g. V2-CH5-CODE-T02 for kst_probflow_v2) before any "
            "execution"
        )


def _fail(message: str) -> None:
    raise ValueError(f"formal matrix: {message}")


def _validate_models(chapter: str, raw: Dict) -> None:
    models = raw.get("models")
    if not isinstance(models, list) or not models:
        _fail("models must be a non-empty list")
    gate = CHAPTER_GATES[chapter]
    seen = set()
    baselines = []
    ours = []
    for model in models:
        if not isinstance(model, dict) or "model_id" not in model:
            _fail("each model entry must be a mapping with model_id")
        model_id = model["model_id"]
        if model_id in FORBIDDEN_MODEL_IDS:
            _fail(
                f"legacy own-model id {model_id!r} is forbidden in formal "
                "matrices (historical audit only)"
            )
        if model_id in seen:
            _fail(f"duplicate model_id {model_id!r}")
        seen.add(model_id)
        family = model.get("family")
        if family == "baseline":
            baselines.append(model)
        elif family == "ours":
            ours.append(model)
        else:
            _fail(f"model {model_id!r} has invalid family {family!r}")
        if not model.get("head_type"):
            _fail(f"model {model_id!r} must declare head_type")

    allowed_baselines = gate["baselines"]
    for model in baselines:
        if model["model_id"] not in allowed_baselines:
            _fail(
                f"model {model['model_id']!r} is not a {chapter} baseline "
                f"(allowed: {sorted(allowed_baselines)})"
            )
    expected_count = gate["baseline_count"]
    if len(baselines) != expected_count:
        _fail(
            f"{chapter} requires exactly {expected_count} baselines, found "
            f"{len(baselines)}: {[m['model_id'] for m in baselines]}"
        )
    expected_ours = gate["ours"]
    got_ours = tuple(m["model_id"] for m in ours)
    if got_ours != expected_ours:
        _fail(f"{chapter} ours must be exactly {list(expected_ours)}, found {list(got_ours)}")

    for model in models:
        status = str(model.get("status", "active"))
        if status not in {"active", "planned"}:
            _fail(f"model {model['model_id']!r} has invalid status {status!r}")
        if status == "planned":
            if model["family"] != "ours":
                _fail(f"planned status is reserved for ours models, got {model['model_id']!r}")
            spec = None
            try:
                spec = get_model_spec(model["model_id"])
            except KeyError:
                pass
            if spec is not None:
                _fail(
                    f"planned model {model['model_id']!r} is already registered "
                    f"as {spec.status}; remove the planned flag"
                )
            continue
        spec = get_model_spec(model["model_id"])
        if spec.status not in {"pilot_ready", "enabled"}:
            _fail(
                f"model {model['model_id']!r} registry status is "
                f"{spec.status!r}; not_implemented models cannot enter formal "
                "matrices"
            )


def _validate_protocols(chapter: str, raw: Dict) -> None:
    protocols = raw.get("protocols")
    if not isinstance(protocols, dict) or not protocols:
        _fail("protocols must be a non-empty mapping")
    if set(protocols) != set(PROTOCOL_CONTRACT):
        _fail(
            f"protocols must be exactly the six-contract set {sorted(PROTOCOL_CONTRACT)}, "
            f"found {sorted(protocols)}"
        )
    for protocol_id, entry in protocols.items():
        if entry.get("dataset") != protocol_id:
            _fail(f"protocol {protocol_id!r} dataset field must equal the protocol id")
        windows = (entry.get("history_len"), entry.get("pred_len"), entry.get("stride"))
        expected = PROTOCOL_CONTRACT[protocol_id]
        if windows != expected:
            _fail(
                f"protocol {protocol_id!r} windows {windows} violate the A.1 "
                f"contract {expected}"
            )
        conditions = entry.get("conditions")
        if not isinstance(conditions, list) or not conditions:
            _fail(f"protocol {protocol_id!r} must declare a non-empty conditions list")
        got = set()
        for condition in conditions:
            if not condition.get("condition_id"):
                _fail(f"protocol {protocol_id!r} condition missing condition_id")
            got.add((condition.get("missing_mode"), float(condition.get("target_missing_rate"))))
        expected_conditions = (
            METROPT_CH3_CONDITIONS
            if (chapter == "ch3" and protocol_id == "metropt3_chrono_502030_v2")
            else EXTERNAL_CONDITION
        )
        if got != expected_conditions:
            _fail(
                f"protocol {protocol_id!r} conditions {sorted(got)} violate the "
                f"A.1 condition contract {sorted(expected_conditions)}"
            )


def _validate_schema_fields(chapter: str, raw: Dict) -> None:
    if raw.get("schema") != "formal-matrix-v1":
        _fail(f"schema must be 'formal-matrix-v1'")
    if raw.get("chapter") != chapter:
        _fail(f"chapter field must be {chapter!r}")
    if raw.get("track") != CHAPTER_GATES[chapter]["track"]:
        _fail(
            f"track must be {CHAPTER_GATES[chapter]['track']!r} for {chapter}"
        )
    if not raw.get("matrix_id"):
        _fail("matrix_id is required")
    if not raw.get("recipe_version"):
        _fail("recipe_version is required")
    if not raw.get("selection_metric"):
        _fail("selection_metric is required")
    recipe = raw.get("recipe")
    if not isinstance(recipe, dict):
        _fail("recipe must be a mapping")
    missing_recipe = [f for f in _REQUIRED_RECIPE_FIELDS if f not in recipe]
    if missing_recipe:
        _fail(f"recipe missing explicit fields {missing_recipe}")
    seeds = raw.get("seeds")
    if not isinstance(seeds, dict):
        _fail("seeds must be a mapping")
    missing_seeds = [f for f in _REQUIRED_SEED_FIELDS if f not in seeds]
    if missing_seeds:
        _fail(f"seeds missing explicit fields {missing_seeds}")


def validate_formal_matrix(raw: Dict, chapter: str) -> None:
    """Validate a parsed formal-matrix mapping against the chapter gates.

    Pure function over the raw dict so tests and tooling can validate mutated
    copies; ``load_formal_matrix`` additionally enforces that only the three
    authoritative entries can reach the formal runner.
    """

    if not isinstance(raw, dict):
        _fail("matrix root must be a mapping")
    _validate_schema_fields(chapter, raw)
    _validate_models(chapter, raw)
    _validate_protocols(chapter, raw)


def load_formal_matrix(path, chapter: Optional[str] = None) -> FormalMatrix:
    """Load and validate one authoritative formal matrix.

    ``chapter`` is required unless ``path`` matches an authoritative entry,
    which also enforces that only the three registered entries can load
    through this API.
    """

    path = Path(path)
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ValueError(f"formal matrix: cannot read {path}: {exc}") from exc
    resolved = str(path.resolve())
    matched_chapter = None
    for candidate_chapter, rel in AUTHORITATIVE_MATRICES.items():
        if resolved == str((Path(__file__).resolve().parents[3] / rel).resolve()):
            matched_chapter = candidate_chapter
            break
    if matched_chapter is None:
        raise ValueError(
            f"formal matrix: {path} is not one of the authoritative entries "
            f"{sorted(AUTHORITATIVE_MATRICES.values())}; legacy "
            "configs/pilot matrices are historical-audit-only and cannot be "
            "loaded by the formal runner"
        )
    chapter = chapter or matched_chapter
    if chapter != matched_chapter:
        _fail(f"path declares {matched_chapter!r} but chapter={chapter!r} was requested")

    raw = yaml.safe_load(text)
    validate_formal_matrix(raw, chapter)

    return FormalMatrix(
        chapter=chapter,
        track=str(raw["track"]),
        matrix_id=str(raw["matrix_id"]),
        recipe_version=str(raw["recipe_version"]),
        matrix_sha256=hashlib.sha256(text.encode("utf-8")).hexdigest(),
        path=str(path),
        seeds={k: int(v) for k, v in raw["seeds"].items()},
        recipe=dict(raw["recipe"]),
        selection_metric=str(raw["selection_metric"]),
        models=list(raw["models"]),
        protocols={pid: dict(p) for pid, p in raw["protocols"].items()},
    )
