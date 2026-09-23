from dataclasses import dataclass
from typing import Dict, List

from kaf_profiti.models.kaf_profiti import KAFProFITi, KAFProFITiConfig
from kaf_profiti.models.kst_probflow import KSTProbFlow, KSTProbFlowConfig


SCHEME_B_REQUIRED_FIELDS = frozenset(
    {
        "recipe_version",
        "encoder_version",
        "cross_variable_mode",
        "missing_feature_version",
        "split_sha",
        "normalization_sha",
        "mask_sha",
        "target_schema_sha",
        "evaluator_sha",
        "code_sha",
        "patch_lens",
        "freshness_tau",
    }
)


def validate_scheme_b_recipe(recipe):
    """Validate the scientific identity required by Scheme B artifacts."""

    if recipe.get("recipe_version") != "scheme_b_v1":
        raise ValueError("recipe_version must be scheme_b_v1")
    missing = sorted(SCHEME_B_REQUIRED_FIELDS - set(recipe))
    if missing:
        raise ValueError(f"missing Scheme B identity fields: {missing}")
    empty = sorted(
        field for field in SCHEME_B_REQUIRED_FIELDS
        if recipe.get(field) is None or recipe.get(field) == ""
    )
    if empty:
        raise ValueError(f"empty Scheme B identity fields: {empty}")
    if recipe.get("cross_variable_mode") not in {"identity", "fla", "missing_graph", "gru_mixer", "missing_sensor_mixer"}:
        raise ValueError("cross_variable_mode must select exactly one block")
    if recipe.get("cross_variable_mode") == "gru_mixer":
        for field in ("gru_hidden", "gru_bottleneck_ratio", "gru_use_forward_fill", "gru_direct_residual"):
            if field not in recipe:
                raise ValueError(f"gru_mixer requires {field}")
        if int(recipe["gru_hidden"]) <= 0 or float(recipe["gru_bottleneck_ratio"]) <= 0:
            raise ValueError("gru_mixer dimensions must be positive")
    if recipe.get("cross_variable_mode") == "missing_sensor_mixer" and int(recipe.get("mixer_layers", 0)) <= 0:
        raise ValueError("missing_sensor_mixer requires positive mixer_layers")
    if recipe.get("model_id") == "kst_flow_v2":
        if recipe.get("flow_order") != "horizon_major_sensor_minor":
            raise ValueError("kst_flow_v2 requires horizon_major_sensor_minor flow_order")
        if "lambda_point" not in recipe:
            raise ValueError("kst_flow_v2 requires lambda_point")


@dataclass(frozen=True)
class ModelSpec:
    name: str
    display_name: str
    status: str
    category: str
    #: faithful | adapted | adapted_profiti | own | "" (unset)
    implementation: str = ""
    #: Plain-text citation of the source mechanism; no URLs (portability rule).
    source_identity: str = ""
    #: Whether the mechanism consumes real timestamps from T_obs.
    requires_time_input: bool = False
    #: Preregistered missing-data adapter description (history-only scope).
    adapter: str = ""


_MODEL_SPECS: Dict[str, ModelSpec] = {
    "tcn_gaussian": ModelSpec(
        "tcn_gaussian",
        "TCN-Gaussian",
        "pilot_ready",
        "baseline",
        implementation="faithful",
        source_identity=(
            "Causal dilated TCN encoder (Bai et al., 2018) with an "
            "independent diagonal Gaussian prediction head; this repository's "
            "own comparison implementation of the declared regular-grid "
            "convolutional probabilistic baseline with no further "
            "simplification"
        ),
        requires_time_input=False,
        adapter=(
            "regular-grid assumption: features are concat(X*M, M, context) on "
            "the observation index grid with no imputation; missing positions "
            "enter as zeros with the mask channel; real timestamps are ignored"
        ),
    ),
    "patchtst_gaussian": ModelSpec(
        "patchtst_gaussian",
        "PatchTST-Gaussian",
        "pilot_ready",
        "baseline",
        implementation="adapted",
        source_identity=(
            "PatchTST (Nie et al., 2023) patching with a Transformer encoder "
            "over patch tokens plus an independent Gaussian head; adapted: a "
            "compact per-sensor patch Transformer (channel-stacked patch "
            "tokens, few encoder layers) instead of the full "
            "channel-independent PatchTST backbone with RevIN and "
            "decomposition"
        ),
        requires_time_input=False,
        adapter=(
            "regular-grid assumption: features are concat(X*M, M) on the "
            "observation index grid with no imputation; missing positions "
            "enter as zeros with the mask channel; real timestamps are ignored"
        ),
    ),
    "gru_d_gaussian": ModelSpec(
        "gru_d_gaussian",
        "GRU-D + Gaussian",
        "pilot_ready",
        "baseline",
        implementation="adapted",
        source_identity=(
            "GRU-D (Che et al., 2018): the model consumes the observation "
            "mask, the elapsed time since the last observation and a "
            "learnable exponential input decay toward the train mean, "
            "followed by a unified diagonal Gaussian prediction head; "
            "adapted: one learnable non-negative decay rate per sensor "
            "instead of a per-feature affine rate map, and no hidden-state "
            "decay term"
        ),
        requires_time_input=True,
        adapter=(
            "native sparse input: missing values decay as "
            "exp(-softplus(rate)*delta_t) toward the train-only fill value "
            "(0.0 in the frozen normalized space); delta_t follows the GRU-D "
            "recursion over the final shared mask"
        ),
    ),
    "ode_rnn_gaussian": ModelSpec(
        "ode_rnn_gaussian",
        "ODE-RNN + Gaussian",
        "pilot_ready",
        "baseline",
        implementation="adapted",
        source_identity=(
            "ODE-RNN (Rubanova et al., 2019, latent ODE): the hidden state "
            "evolves by the real elapsed time between historical observations "
            "and up to the forecast origin, with a GRUCell update at each "
            "observation step, plus an independent Gaussian head; adapted: "
            "fixed-count Euler integration with a learned tanh vector field "
            "instead of a black-box adjoint ODE solver"
        ),
        requires_time_input=True,
        adapter=(
            "native sparse input: values enter as X*M with the mask as an "
            "input channel; the hidden state integrates over real T_obs gaps "
            "and the gap to the forecast origin T_q[:, 0]; no other future "
            "field is read"
        ),
    ),
    "grafiti_gaussian": ModelSpec(
        "grafiti_gaussian",
        "GraFITi + Gaussian",
        "pilot_ready",
        "baseline",
        implementation="adapted",
        source_identity=(
            "GraFITi (Yalavarthi et al., 2024): irregular time series "
            "forecasting as graph message passing that couples sensors and "
            "observation times; adapted: a learnable static sensor adjacency "
            "with per-gap exponential time decay of the propagated state over "
            "the real T_obs grid, instead of the original sparse bipartite "
            "time-variable graph and learned edge weights"
        ),
        requires_time_input=True,
        adapter=(
            "native sparse input: features are concat(X*M, M, context) per "
            "observation step; propagation strength decays as "
            "exp(-softplus(rate)*dt) with the real inter-observation gap dt, "
            "so no values are imputed and no future field is read"
        ),
    ),
    "li_tcn": ModelSpec(
        "li_tcn",
        "LI+TCN",
        "pilot_ready",
        "baseline",
        implementation="adapted",
        source_identity=(
            "Linear interpolation over real history timestamps (Che et al., "
            "2018, GRU-D-style interpolation baseline) feeding a causal dilated "
            "TCN encoder (Bai et al., 2018); TCN backbone adapted from the "
            "project's TCN-Gaussian reference with the Gaussian parts removed"
        ),
        requires_time_input=True,
        adapter=(
            "history-only linear interpolation between observed neighbors in "
            "real time; leading gaps and fully unobserved channels use the "
            "train-only fill value (0.0 in the frozen normalized space)"
        ),
    ),
    "ff_gru": ModelSpec(
        "ff_gru",
        "FF+GRU",
        "pilot_ready",
        "baseline",
        implementation="adapted",
        source_identity=(
            "Forward-fill missing-data adapter with a unidirectional GRU "
            "encoder (Cho et al., 2014); last-observation carry-forward inside "
            "the history window only"
        ),
        requires_time_input=False,
        adapter=(
            "history-only forward fill; leading gaps and fully unobserved "
            "channels use the train-only fill value (0.0 in the frozen "
            "normalized space)"
        ),
    ),
    "masked_tcn": ModelSpec(
        "masked_tcn",
        "Masked TCN",
        "pilot_ready",
        "baseline",
        implementation="adapted",
        source_identity=(
            "Masked-input causal TCN: features are concat(X*M, M, context) "
            "with no imputation; TCN backbone adapted from the project's "
            "TCN-Gaussian reference (Bai et al., 2018) with the Gaussian parts "
            "removed"
        ),
        requires_time_input=False,
        adapter=(
            "no fill: masked-out positions are zeroed and the observation mask "
            "is concatenated as input channels, so the model sees exactly what "
            "was observed in history"
        ),
    ),
    "gru_d": ModelSpec(
        "gru_d",
        "GRU-D",
        "pilot_ready",
        "baseline",
        implementation="adapted",
        source_identity=(
            "GRU-D (Che et al., 2018): the model consumes the observation "
            "mask, the elapsed time since the last observation and a learnable "
            "exponential input decay toward the train mean; adapted: one "
            "learnable non-negative decay rate per sensor instead of a "
            "per-feature affine rate map, and no hidden-state decay term"
        ),
        requires_time_input=True,
        adapter=(
            "native sparse input: missing values decay as "
            "exp(-softplus(rate)*delta_t) toward the train-only fill value "
            "(0.0 in the frozen normalized space); delta_t follows the GRU-D "
            "recursion over the final shared mask"
        ),
    ),
    "ode_rnn": ModelSpec(
        "ode_rnn",
        "ODE-RNN",
        "pilot_ready",
        "baseline",
        implementation="adapted",
        source_identity=(
            "ODE-RNN (Rubanova et al., 2019, latent ODE): the hidden state "
            "evolves by the real elapsed time between historical observations "
            "and is updated by a GRUCell at each observation step; adapted: "
            "Euler integration with a learned tanh vector field instead of a "
            "black-box adjoint ODE solver. The Euler expansion is multiplicative over the "
            "time gap, which makes it sensitive to gradient scale; training "
            "therefore relies on the shared global grad-norm clip (1.0, the "
            "repository's established recipe) — without clipping this adapted "
            "implementation diverges (2026-09-17 local diagnostic: grad-norm "
            "peaks ~6.6e7, valid MAE 9.30 vs persistence floor 0.9159)"
        ),
        requires_time_input=True,
        adapter=(
            "native sparse input: values enter as X*M with the mask as an "
            "input channel; the hidden state integrates over real T_obs gaps "
            "within the history window and never reads T_q or any future field"
        ),
    ),
    "kst_light": ModelSpec(
        "kst_light",
        "KST-Light",
        "pilot_ready",
        "own",
        implementation="own",
        source_identity=(
            "Project model: MultiScaleKAFEncoder asynchronous regularized-"
            "history encoder + unified lightweight Linear/MLP point head"
        ),
        requires_time_input=False,
        adapter=(
            "history-only encoder consumption; missing history handled inside "
            "the encoder through the observation mask, no target or future "
            "input"
        ),
    ),
    "mtan": ModelSpec("mtan", "mTAN", "not_implemented", "baseline"),
    "tpatchgnn": ModelSpec("tpatchgnn", "tPatchGNN", "not_implemented", "baseline"),
    "grafiti": ModelSpec("grafiti", "GraFITi", "not_implemented", "baseline"),
    "profiti": ModelSpec(
        "profiti",
        "ProFITi",
        "pilot_ready",
        "baseline",
        implementation="adapted_profiti",
        source_identity=(
            "ProFITi (Yalavarthi et al., 2024): probabilistic forecasting of "
            "irregular time series via a conditional normalizing flow over "
            "the query vector (triangular attention flow trained with joint "
            "NLL); adapted_profiti: the project's ProFITiFlowHead flow and "
            "QueryConditionAdapter conditioning driven by a GRU observation "
            "encoder, instead of the original bidirectional encoder stack; "
            "NLL and samples come from this same trained flow"
        ),
        requires_time_input=True,
        adapter=(
            "native sparse input: features are concat(X*M, M, T_obs, context) "
            "so the model sees real observation timestamps; query "
            "conditioning uses T_q only as the forecast time grid"
        ),
    ),
    "kafnet": ModelSpec("kafnet", "KAFNet", "not_implemented", "baseline"),
    "kafnet_gaussian": ModelSpec(
        "kafnet_gaussian", "KAFNet + Gaussian Head", "not_implemented", "ablation"
    ),
    "kaf_profiti_marginal": ModelSpec(
        "kaf_profiti_marginal",
        "KAFNet + ProFITi Marginal Flow",
        "not_implemented",
        "ablation",
    ),
    "kaf_profiti_joint": ModelSpec(
        "kaf_profiti_joint", "KAFNet + ProFITi Joint Flow", "enabled", "final"
    ),
    "kst_probflow": ModelSpec(
        "kst_probflow",
        "KST ProbFlow",
        "enabled",
        "final",
        implementation="own",
        source_identity=(
            "Project model KST ProbFlow: MultiScaleKAFEncoder asynchronous "
            "regularized-history encoder + dynamic sensor graph + "
            "QueryConditionAdapter with a Student-t low-rank copula flow head "
            "(joint NLL with seeded sampling); NLL and samples come from the "
            "same trained head"
        ),
        requires_time_input=True,
        adapter=(
            "native sparse input: the encoder consumes the shared observation "
            "mask and real T_obs/T_q event times; no imputation, and no "
            "target or future field enters the prediction paths"
        ),
    ),
    "kst_light_v2": ModelSpec(
        "kst_light_v2",
        "KST-Light v2",
        "enabled",
        "own",
        implementation="own",
        source_identity=(
            "Scheme B: causal missingness features, mask-safe hierarchical "
            "multi-scale KAF encoder, exclusive cross-variable block and "
            "last-observation residual point decoder"
        ),
        requires_time_input=True,
        adapter="history-only missingness-aware representation; no target fields",
    ),
    "kst_flow_v2": ModelSpec(
        "kst_flow_v2",
        "KST-Flow v2",
        "enabled",
        "final",
        implementation="own",
        source_identity=(
            "Scheme B: KST-Light v2 representation with QueryConditionAdapter "
            "and ProFITi triangular conditional flow; samples and NLL share "
            "one distribution"
        ),
        requires_time_input=True,
        adapter="history-only missingness-aware representation; no target fields",
    ),
}


def list_model_specs() -> List[ModelSpec]:
    return list(_MODEL_SPECS.values())


def get_model_spec(name: str) -> ModelSpec:
    try:
        return _MODEL_SPECS[name]
    except KeyError as exc:
        raise KeyError(f"Unknown model: {name}") from exc


def create_model(
    name: str,
    num_sensors: int,
    context_dim: int,
    device: str,
    hidden_dim: int = 32,
    te_dim: int = 5,
    kernel_count: int = 4,
    n_layers: int = 2,
    n_heads: int = 2,
    flow_layers: int = 2,
    preconv_dim: int = 8,
    lambda_point: float = 0.1,
    patch_lens="12,24,48",
    graph_layers: int = 1,
    copula_rank: int = 32,
    lambda_quantile: float = 0.2,
    lambda_risk: float = 0.05,
    attention_diag_floor: float = 0.05,
    sample_clip: float = 20.0,
    inverse_clip: float = 1_000_000.0,
):
    spec = get_model_spec(name)
    if spec.status != "enabled":
        raise NotImplementedError(f"Model {name} is registered as {spec.status}")
    if name == "kst_probflow":
        if isinstance(patch_lens, str):
            patch_lens_tuple = tuple(int(part) for part in patch_lens.split(",") if part.strip())
        else:
            patch_lens_tuple = tuple(int(part) for part in patch_lens)
        config = KSTProbFlowConfig(
            num_sensors=num_sensors,
            context_dim=context_dim,
            hidden_dim=hidden_dim,
            te_dim=te_dim,
            kernel_count=kernel_count,
            n_layers=n_layers,
            n_heads=n_heads,
            preconv_dim=preconv_dim,
            patch_lens=patch_lens_tuple,
            graph_layers=graph_layers,
            copula_rank=copula_rank,
            lambda_point=lambda_point,
            lambda_quantile=lambda_quantile,
            lambda_risk=lambda_risk,
            sample_clip=sample_clip,
            attention_diag_floor=attention_diag_floor,
            device=device,
        )
        return KSTProbFlow(config)
    if name == "kst_light_v2":
        from kaf_profiti.models.kst_light import KSTLightV2, KSTLightV2Config

        if isinstance(patch_lens, str):
            patch_lens_tuple = tuple(int(part) for part in patch_lens.split(",") if part.strip())
        else:
            patch_lens_tuple = tuple(int(part) for part in patch_lens)
        return KSTLightV2(
            KSTLightV2Config(
                num_sensors=num_sensors,
                context_dim=context_dim,
                hidden_dim=hidden_dim,
                te_dim=te_dim,
                kernel_count=kernel_count,
                n_layers=n_layers,
                n_heads=n_heads,
                preconv_dim=preconv_dim,
                patch_lens=patch_lens_tuple,
                cross_variable_mode="fla",
                pred_len=24,
            )
        ).to(device)
    if name == "kst_flow_v2":
        from kaf_profiti.models.kst_flow import KSTFlowV2, KSTFlowV2Config

        if isinstance(patch_lens, str):
            patch_lens_tuple = tuple(int(part) for part in patch_lens.split(",") if part.strip())
        else:
            patch_lens_tuple = tuple(int(part) for part in patch_lens)
        return KSTFlowV2(
            KSTFlowV2Config(
                num_sensors=num_sensors,
                context_dim=context_dim,
                hidden_dim=hidden_dim,
                te_dim=te_dim,
                kernel_count=kernel_count,
                n_layers=n_layers,
                n_heads=n_heads,
                flow_layers=flow_layers,
                preconv_dim=preconv_dim,
                patch_lens=patch_lens_tuple,
                lambda_point=lambda_point,
                device=device,
            )
        ).to(device)
    if name != "kaf_profiti_joint":
        raise NotImplementedError(f"Model {name} has no implementation")
    config = KAFProFITiConfig(
        num_sensors=num_sensors,
        context_dim=context_dim,
        hidden_dim=hidden_dim,
        te_dim=te_dim,
        kernel_count=kernel_count,
        n_layers=n_layers,
        n_heads=n_heads,
        flow_layers=flow_layers,
        preconv_dim=preconv_dim,
        lambda_point=lambda_point,
        marginal_training=False,
        attention_diag_floor=attention_diag_floor,
        sample_clip=sample_clip,
        inverse_clip=inverse_clip,
        device=device,
    )
    return KAFProFITi(config)
