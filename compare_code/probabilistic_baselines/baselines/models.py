import math
from typing import Dict, Iterable, Tuple

import torch
from torch import Tensor, nn
import torch.nn.functional as F

from kaf_profiti.experiments.model_api import UnifiedFlowModel, UnifiedGaussianModel
from kaf_profiti.models.kafnet_encoder import KAFNetEncoder
from kaf_profiti.models.profiti_flow_head import ProFITiFlowHead
from kaf_profiti.models.query_condition_adapter import QueryConditionAdapter


MODEL_NAMES = (
    "patchtst_gaussian",
    "ode_rnn",
    "tpatchgnn",
    "profiti",
    "kafnet",
)


def list_baseline_models():
    return list(MODEL_NAMES)


def _safe_mask(mask: Tensor) -> Tensor:
    return torch.nan_to_num(mask.float(), nan=0.0, posinf=1.0, neginf=0.0).clamp(0.0, 1.0)


def _masked_last(x: Tensor, mask: Tensor) -> Tensor:
    valid_any = mask.sum(dim=-1) > 0
    row_valid = valid_any.float()
    idx = torch.arange(x.shape[1], device=x.device).view(1, -1)
    last_idx = (idx * row_valid.long()).max(dim=1).values
    return x[torch.arange(x.shape[0], device=x.device), last_idx]


def _masked_summary(x: Tensor, mask: Tensor) -> Tensor:
    mask = _safe_mask(mask)
    count = mask.sum(dim=1).clamp_min(1.0)
    mean = (x * mask).sum(dim=1) / count
    centered = (x - mean[:, None, :]) * mask
    std = torch.sqrt(centered.pow(2).sum(dim=1) / count).clamp_max(1e6)
    last = _masked_last(x * mask, mask)
    missing = 1.0 - mask.mean(dim=1)
    return torch.cat([mean, std, last, missing], dim=-1)


class BaseGaussianForecastModel(UnifiedGaussianModel):
    """Diagonal Gaussian baselines that also speak the unified pilot API.

    ``forward`` keeps the legacy call signature for the standalone trainer;
    ``gaussian_params`` adapts it to the unified batch contract so
    ``predict_point``/``batch_nll``/``sample_flat``/``interval95_flat``/``loss``
    all come from one shared distribution with the unified scale
    parameterization (``softplus + min_scale``), NLL denominator and
    ``mean +/- Z95 * scale`` interval.
    """

    model_name = "base"

    def __init__(
        self,
        num_sensors: int,
        context_dim: int,
        pred_len: int,
        hidden_dim: int = 64,
        min_scale: float = 0.05,
        **_: object,
    ):
        super().__init__()
        self.num_sensors = int(num_sensors)
        self.context_dim = int(context_dim)
        self.pred_len = int(pred_len)
        self.hidden_dim = int(hidden_dim)
        self.min_scale = float(min_scale)

    def forward(
        self,
        x_obs: Tensor,
        mask: Tensor,
        context: Tensor = None,
        t_obs: Tensor = None,
        t_q: Tensor = None,
    ) -> Tuple[Tensor, Tensor]:
        raise NotImplementedError

    def gaussian_params(self, batch) -> Tuple[Tensor, Tensor]:
        return self.forward(
            batch.X_obs, batch.M_obs, batch.context, t_obs=batch.T_obs, t_q=batch.T_q
        )

    def nll(self, y: Tensor, mean: Tensor, scale: Tensor, mask: Tensor = None) -> Tensor:
        if mask is None:
            mask = torch.ones_like(y)
        mask = _safe_mask(mask)
        log_prob = -0.5 * ((y - mean) / scale).pow(2) - torch.log(scale) - 0.5 * math.log(
            2.0 * math.pi
        )
        return -((log_prob * mask).sum() / mask.sum().clamp_min(1.0))

    @staticmethod
    def mse(y: Tensor, mean: Tensor, mask: Tensor = None) -> Tensor:
        if mask is None:
            mask = torch.ones_like(y)
        mask = _safe_mask(mask)
        return (((mean - y) ** 2) * mask).sum() / mask.sum().clamp_min(1.0)

    def sample(
        self,
        x_obs: Tensor,
        mask: Tensor,
        context: Tensor = None,
        nsamples: int = 100,
        t_obs: Tensor = None,
        t_q: Tensor = None,
    ) -> Tensor:
        mean, scale = self.forward(x_obs, mask, context, t_obs=t_obs, t_q=t_q)
        eps = torch.randn(
            mean.shape[0],
            int(nsamples),
            mean.shape[1],
            mean.shape[2],
            device=mean.device,
            dtype=mean.dtype,
        )
        return mean.unsqueeze(1) + scale.unsqueeze(1) * eps

    @staticmethod
    def risk_score(mean: Tensor, scale: Tensor) -> Tensor:
        raw = mean.abs().mean(dim=(1, 2)) + 0.5 * scale.clamp_min(0.0).mean(dim=(1, 2))
        return torch.sigmoid(raw)

    def _shape_output(self, raw: Tensor, batch_size: int) -> Tuple[Tensor, Tensor]:
        raw = raw.view(batch_size, self.pred_len, self.num_sensors, 2)
        mean = raw[..., 0]
        scale = F.softplus(raw[..., 1]) + self.min_scale
        return mean, scale


class PatchTSTGaussian(BaseGaussianForecastModel):
    model_name = "patchtst_gaussian"

    IMPLEMENTATION = "adapted"
    SOURCE_IDENTITY = (
        "PatchTST (Nie et al., 2023) patching with a Transformer encoder over "
        "patch tokens plus an independent Gaussian head; adapted: a compact "
        "per-sensor patch Transformer (channel-stacked patch tokens, few "
        "encoder layers) instead of the full channel-independent PatchTST "
        "backbone with RevIN and decomposition"
    )
    REQUIRES_TIME_INPUT = False
    ADAPTER = (
        "regular-grid assumption: features are concat(X*M, M) on the "
        "observation index grid with no imputation; missing positions enter as "
        "zeros with the mask channel; real timestamps are ignored"
    )

    def __init__(
        self,
        num_sensors: int,
        context_dim: int,
        pred_len: int,
        hidden_dim: int = 64,
        patch_len: int = 16,
        patch_stride: int = 8,
        n_heads: int = 4,
        levels: int = 2,
        dropout: float = 0.1,
        **kwargs: object,
    ):
        super().__init__(num_sensors, context_dim, pred_len, hidden_dim, **kwargs)
        self.patch_len = max(1, int(patch_len))
        self.patch_stride = max(1, int(patch_stride))
        self.patch_proj = nn.Linear(self.patch_len * 2, hidden_dim)
        encoder_layer = nn.TransformerEncoderLayer(
            d_model=hidden_dim,
            nhead=max(1, int(n_heads)),
            dim_feedforward=hidden_dim * 4,
            dropout=float(dropout),
            batch_first=True,
            activation="gelu",
        )
        self.encoder = nn.TransformerEncoder(encoder_layer, num_layers=max(1, int(levels)))
        self.context_proj = nn.Linear(context_dim, hidden_dim) if context_dim > 0 else None
        self.head = nn.Sequential(
            nn.LayerNorm(hidden_dim),
            nn.Linear(hidden_dim, hidden_dim),
            nn.GELU(),
            nn.Linear(hidden_dim, pred_len * 2),
        )

    def _patches(self, x: Tensor, mask: Tensor) -> Tensor:
        if x.shape[1] < self.patch_len:
            pad = self.patch_len - x.shape[1]
            x = F.pad(x, (0, 0, pad, 0))
            mask = F.pad(mask, (0, 0, pad, 0))
        tokens = torch.cat([x * mask, mask], dim=-1).transpose(1, 2)
        patches = tokens.unfold(dimension=-1, size=self.patch_len, step=self.patch_stride)
        patches = patches.transpose(1, 2).contiguous()
        batch_size, patch_count, channels, patch_len = patches.shape
        patches = patches.view(batch_size, patch_count, channels // 2, 2, patch_len)
        patches = patches.permute(0, 2, 1, 3, 4).reshape(
            batch_size * self.num_sensors, patch_count, 2 * patch_len
        )
        return patches

    def forward(self, x_obs, mask, context=None, t_obs=None, t_q=None):
        batch_size = x_obs.shape[0]
        tokens = self.patch_proj(self._patches(x_obs, _safe_mask(mask)))
        encoded = self.encoder(tokens).mean(dim=1)
        encoded = encoded.view(batch_size, self.num_sensors, self.hidden_dim)
        if self.context_proj is not None and context is not None:
            encoded = encoded + self.context_proj(context)[:, None, :]
        raw = self.head(encoded).view(batch_size, self.num_sensors, self.pred_len, 2)
        raw = raw.permute(0, 2, 1, 3).contiguous()
        return self._shape_output(raw, batch_size)


class ODERNNGaussian(BaseGaussianForecastModel):
    model_name = "ode_rnn"

    IMPLEMENTATION = "adapted"
    SOURCE_IDENTITY = (
        "ODE-RNN (Rubanova et al., 2019, latent ODE): the hidden state evolves "
        "by the real elapsed time between historical observations and up to "
        "the forecast origin, with a GRUCell update at each observation step, "
        "plus an independent Gaussian head; adapted: fixed-count Euler "
        "integration with a learned tanh vector field instead of a black-box "
        "adjoint ODE solver"
    )
    REQUIRES_TIME_INPUT = True
    ADAPTER = (
        "native sparse input: values enter as X*M with the mask as an input "
        "channel; the hidden state integrates over real T_obs gaps and the gap "
        "to the forecast origin T_q[:, 0]; no other future field is read"
    )

    def __init__(
        self,
        num_sensors: int,
        context_dim: int,
        pred_len: int,
        hidden_dim: int = 64,
        ode_steps: int = 1,
        **kwargs: object,
    ):
        super().__init__(num_sensors, context_dim, pred_len, hidden_dim, **kwargs)
        self.input_proj = nn.Linear(num_sensors * 2 + context_dim, hidden_dim)
        self.gru = nn.GRUCell(hidden_dim, hidden_dim)
        self.ode = nn.Sequential(
            nn.Linear(hidden_dim, hidden_dim),
            nn.Tanh(),
            nn.Linear(hidden_dim, hidden_dim),
        )
        self.ode_steps = max(1, int(ode_steps))
        self.head = nn.Sequential(
            nn.LayerNorm(hidden_dim),
            nn.Linear(hidden_dim, hidden_dim),
            nn.ReLU(True),
            nn.Linear(hidden_dim, pred_len * num_sensors * 2),
        )

    def _evolve(self, h: Tensor, dt: Tensor) -> Tensor:
        step = dt.clamp_min(0.0).view(-1, 1) / float(self.ode_steps)
        for _ in range(self.ode_steps):
            h = h + step * self.ode(h)
        return h

    def forward(self, x_obs, mask, context=None, t_obs=None, t_q=None):
        batch_size, history_len, _ = x_obs.shape
        if context is None:
            context = x_obs.new_zeros(batch_size, 0)
        if t_obs is None:
            t_obs = torch.arange(history_len, device=x_obs.device, dtype=x_obs.dtype).repeat(batch_size, 1)
        h = x_obs.new_zeros(batch_size, self.hidden_dim)
        last_t = t_obs[:, 0]
        for idx in range(history_len):
            dt = t_obs[:, idx] - last_t
            h = self._evolve(h, dt)
            features = torch.cat([x_obs[:, idx] * mask[:, idx], mask[:, idx], context], dim=-1)
            h = self.gru(self.input_proj(features), h)
            last_t = t_obs[:, idx]
        if t_q is not None and t_q.numel() > 0:
            h = self._evolve(h, t_q[:, 0] - last_t)
        raw = self.head(h)
        return self._shape_output(raw, batch_size)


class TPatchGNNGaussian(BaseGaussianForecastModel):
    model_name = "tpatchgnn"

    def __init__(
        self,
        num_sensors: int,
        context_dim: int,
        pred_len: int,
        hidden_dim: int = 64,
        patch_len: int = 12,
        patch_stride: int = 6,
        graph_layers: int = 1,
        **kwargs: object,
    ):
        super().__init__(num_sensors, context_dim, pred_len, hidden_dim, **kwargs)
        self.patch_len = max(1, int(patch_len))
        self.patch_stride = max(1, int(patch_stride))
        self.token_proj = nn.Linear(5, hidden_dim)
        self.static_adj = nn.Parameter(torch.zeros(num_sensors, num_sensors))
        self.graph_layers = max(1, int(graph_layers))
        self.context_proj = nn.Linear(context_dim, hidden_dim) if context_dim > 0 else None
        self.head = nn.Sequential(
            nn.LayerNorm(hidden_dim),
            nn.Linear(hidden_dim, hidden_dim),
            nn.ReLU(True),
            nn.Linear(hidden_dim, pred_len * 2),
        )

    def _patch_stats(self, x: Tensor, mask: Tensor, t_obs: Tensor = None) -> Tensor:
        batch_size, history_len, num_sensors = x.shape
        if history_len < self.patch_len:
            pad = self.patch_len - history_len
            x = F.pad(x, (0, 0, pad, 0))
            mask = F.pad(mask, (0, 0, pad, 0))
            history_len = x.shape[1]
        if t_obs is None:
            t_obs = torch.arange(history_len, device=x.device, dtype=x.dtype).repeat(batch_size, 1)
        elif t_obs.shape[1] < history_len:
            pad = history_len - t_obs.shape[1]
            t_obs = F.pad(t_obs, (pad, 0))
        patches = []
        for start in range(0, history_len - self.patch_len + 1, self.patch_stride):
            end = start + self.patch_len
            xv = x[:, start:end]
            mv = _safe_mask(mask[:, start:end])
            tv = t_obs[:, start:end, None].expand(-1, -1, num_sensors)
            count = mv.sum(dim=1).clamp_min(1.0)
            mean = (xv * mv).sum(dim=1) / count
            std = torch.sqrt(((xv - mean[:, None, :]) * mv).pow(2).sum(dim=1) / count)
            last = _masked_last(xv * mv, mv)
            missing = 1.0 - mv.mean(dim=1)
            span = (tv.max(dim=1).values - tv.min(dim=1).values) * (count > 0).float()
            patches.append(torch.stack([mean, std, last, missing, span], dim=-1))
        return torch.stack(patches, dim=2).mean(dim=2)

    def forward(self, x_obs, mask, context=None, t_obs=None, t_q=None):
        batch_size = x_obs.shape[0]
        z = self.token_proj(self._patch_stats(x_obs, mask, t_obs=t_obs))
        if self.context_proj is not None and context is not None:
            z = z + self.context_proj(context)[:, None, :]
        for _ in range(self.graph_layers):
            dynamic = torch.softmax(torch.bmm(z, z.transpose(1, 2)) / math.sqrt(self.hidden_dim), dim=-1)
            static = torch.softmax(self.static_adj, dim=-1).unsqueeze(0)
            adj = 0.5 * dynamic + 0.5 * static
            z = z + torch.bmm(adj, z)
        raw = self.head(z).view(batch_size, self.num_sensors, self.pred_len, 2)
        raw = raw.permute(0, 2, 1, 3).contiguous()
        return self._shape_output(raw, batch_size)


class KAFNetGaussian(BaseGaussianForecastModel):
    model_name = "kafnet"

    def __init__(
        self,
        num_sensors: int,
        context_dim: int,
        pred_len: int,
        hidden_dim: int = 64,
        te_dim: int = 10,
        kernel_count: int = 4,
        n_layers: int = 2,
        n_heads: int = 2,
        preconv_dim: int = 16,
        **kwargs: object,
    ):
        super().__init__(num_sensors, context_dim, pred_len, hidden_dim, **kwargs)
        self.encoder = KAFNetEncoder(
            num_sensors=num_sensors,
            hidden_dim=hidden_dim,
            kernel_count=kernel_count,
            time_dim=te_dim,
            n_layers=n_layers,
            n_heads=n_heads,
            preconv_dim=preconv_dim,
            context_dim=context_dim,
        )
        self.adapter = QueryConditionAdapter(num_sensors, hidden_dim, te_dim, context_dim=context_dim)
        self.head = nn.Linear(hidden_dim, 2)

    def forward(self, x_obs, mask, context=None, t_obs=None, t_q=None):
        batch_size = x_obs.shape[0]
        if t_obs is None:
            t_obs = torch.arange(x_obs.shape[1], device=x_obs.device, dtype=x_obs.dtype).repeat(batch_size, 1)
        if t_q is None:
            t_q = torch.arange(self.pred_len, device=x_obs.device, dtype=x_obs.dtype).repeat(batch_size, 1)
        z = self.encoder(x_obs, t_obs, mask, context)
        channel_ids = self.adapter.build_time_first_channel_ids(self.pred_len, device=x_obs.device)
        hq = self.adapter(z, t_q, channel_ids, context)
        raw = self.head(hq).view(batch_size, self.pred_len, self.num_sensors, 2)
        return self._shape_output(raw, batch_size)


class ProFITiGaussian(UnifiedFlowModel, BaseGaussianForecastModel):
    """ProFITi conditional-flow baseline on the unified pilot API.

    NLL and samples come from the same trained ``ProFITiFlowHead`` flow: the
    unified ``batch_nll`` re-weights the flow's per-row joint NLL to the
    shared valid-position denominator, and ``predict_point``/
    ``interval95_flat``/``sample_flat`` draw from the identical flow (seeded
    generators make the point prediction deterministic). The legacy
    ``forward``/``nll``/``sample`` keep their cached-hidden contract for the
    standalone trainer and are never used by the unified path.
    """

    model_name = "profiti"

    IMPLEMENTATION = "adapted_profiti"
    SOURCE_IDENTITY = (
        "ProFITi (Yalavarthi et al., 2024): probabilistic forecasting of "
        "irregular time series via a conditional normalizing flow over the "
        "query vector (triangular attention flow trained with joint NLL); "
        "adapted_profiti: the project's ProFITiFlowHead flow and "
        "QueryConditionAdapter conditioning driven by a GRU observation "
        "encoder, instead of the original bidirectional encoder stack; NLL and "
        "samples come from this same trained flow"
    )
    REQUIRES_TIME_INPUT = True
    ADAPTER = (
        "native sparse input: features are concat(X*M, M, T_obs, context) so "
        "the model sees real observation timestamps; query conditioning uses "
        "T_q only as the forecast time grid"
    )

    def __init__(
        self,
        num_sensors: int,
        context_dim: int,
        pred_len: int,
        hidden_dim: int = 64,
        te_dim: int = 10,
        flow_layers: int = 2,
        attention_diag_floor: float = 0.05,
        sample_clip: float = 30.0,
        inverse_clip: float = 1_000_000.0,
        **kwargs: object,
    ):
        super().__init__(num_sensors, context_dim, pred_len, hidden_dim, **kwargs)
        self.obs_proj = nn.Linear(num_sensors * 2 + context_dim + 1, hidden_dim)
        self.gru = nn.GRU(hidden_dim, hidden_dim, batch_first=True)
        self.adapter = QueryConditionAdapter(num_sensors, hidden_dim, te_dim, context_dim=context_dim)
        self.flow_head = ProFITiFlowHead(
            hidden_dim=hidden_dim,
            flow_layers=flow_layers,
            marginal_training=False,
            device=torch.device("cpu"),
            attention_diag_floor=attention_diag_floor,
            sample_clip=sample_clip,
            inverse_clip=inverse_clip,
        )

    def _hidden(self, x_obs, mask, context=None, t_obs=None, t_q=None):
        batch_size, history_len, _ = x_obs.shape
        if context is None:
            context = x_obs.new_zeros(batch_size, 0)
        if t_obs is None:
            t_obs = torch.arange(history_len, device=x_obs.device, dtype=x_obs.dtype).repeat(batch_size, 1)
        if t_q is None:
            t_q = torch.arange(self.pred_len, device=x_obs.device, dtype=x_obs.dtype).repeat(batch_size, 1)
        context_seq = context[:, None, :].expand(batch_size, history_len, context.shape[-1])
        features = torch.cat([x_obs * mask, mask, t_obs[..., None], context_seq], dim=-1)
        _, h = self.gru(self.obs_proj(features))
        z = h[-1].unsqueeze(1).expand(-1, self.num_sensors, -1)
        channel_ids = self.adapter.build_time_first_channel_ids(self.pred_len, device=x_obs.device)
        return self.adapter(z, t_q, channel_ids, context)

    def forward(self, x_obs, mask, context=None, t_obs=None, t_q=None):
        hidden = self._hidden(x_obs, mask, context=context, t_obs=t_obs, t_q=t_q)
        self._last_hidden = hidden
        flat = self.flow_head.base_mean(hidden, torch.ones(hidden.shape[:2], device=hidden.device))
        mean = flat.view(x_obs.shape[0], self.pred_len, self.num_sensors)
        scale = torch.ones_like(mean) * (1.0 + self.min_scale)
        return mean, scale

    def nll(self, y: Tensor, mean: Tensor, scale: Tensor, mask: Tensor = None) -> Tensor:
        if mask is None:
            mask = torch.ones_like(y)
        batch_size = y.shape[0]
        hidden = getattr(self, "_last_hidden", None)
        if hidden is None or hidden.shape[0] != batch_size:
            return super().nll(y, mean, scale, mask)
        return self.flow_head.nll(y.reshape(batch_size, -1), hidden, mask.reshape(batch_size, -1)).mean()

    def sample(self, x_obs, mask, context=None, nsamples: int = 100, t_obs=None, t_q=None):
        hidden = self._hidden(x_obs, mask, context=context, t_obs=t_obs, t_q=t_q)
        self._last_hidden = hidden
        flat_mask = torch.ones(hidden.shape[:2], device=hidden.device)
        samples = self.flow_head.sample(hidden, flat_mask, nsamples=nsamples)
        return samples.view(x_obs.shape[0], int(nsamples), self.pred_len, self.num_sensors)

    # -- unified flow API (CH2.5-P02-T03) ---------------------------------

    def flow_hidden(self, batch) -> Tensor:
        # Fresh conditioning per call: the unified path must not depend on the
        # legacy cached ``_last_hidden``.
        return self._hidden(
            batch.X_obs, batch.M_obs, context=batch.context, t_obs=batch.T_obs, t_q=batch.T_q
        )

    def _flow_nll_rows(self, y_flat: Tensor, hidden: Tensor, mq_flat: Tensor) -> Tensor:
        return self.flow_head.nll(y_flat, hidden, mq_flat)

    def _flow_sample(
        self,
        hidden: Tensor,
        mq_flat: Tensor,
        nsamples: int,
        generator: torch.Generator = None,
    ) -> Tensor:
        return self.flow_head.sample(hidden, mq_flat, nsamples=nsamples, generator=generator)


def create_baseline_model(
    model_name: str,
    num_sensors: int,
    context_dim: int,
    pred_len: int,
    **kwargs: object,
) -> BaseGaussianForecastModel:
    name = model_name.lower()
    registry = {
        "patchtst_gaussian": PatchTSTGaussian,
        "ode_rnn": ODERNNGaussian,
        "tpatchgnn": TPatchGNNGaussian,
        "profiti": ProFITiGaussian,
        "kafnet": KAFNetGaussian,
    }
    if name not in registry:
        raise ValueError(f"Unknown baseline model: {model_name}")
    return registry[name](
        num_sensors=num_sensors,
        context_dim=context_dim,
        pred_len=pred_len,
        **kwargs,
    )
