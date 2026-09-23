import math
from dataclasses import dataclass

import torch
from torch import Tensor, nn
import torch.nn.functional as F


class TTKMN(nn.Module):
    def __init__(self, kernel_count: int = 4):
        super().__init__()
        self.kernel_count = kernel_count
        self.c = nn.Parameter(torch.linspace(0, 1, kernel_count))
        self.log_alpha = nn.Parameter(torch.zeros(kernel_count))
        self.gate = nn.Parameter(torch.zeros(kernel_count))

    def forward(self, t: Tensor, x: Tensor, m: Tensor) -> Tensor:
        alpha = self.log_alpha.exp() + 1e-6
        td = t - self.c.view(1, 1, self.kernel_count)
        weights = torch.exp(-0.5 * td**2 / alpha.view(1, 1, self.kernel_count) ** 2) * m
        attn = weights / (weights.sum(1, keepdim=True) + 1e-8)
        pooled = torch.einsum("blk,bld->bk", attn, x)
        pooled = pooled * torch.sigmoid(self.gate)
        flag = (m.sum(1) > 0).float()
        return torch.cat([pooled, flag], dim=-1)


class PositionalEncoding(nn.Module):
    def __init__(self, dim: int, max_len: int):
        super().__init__()
        pos = torch.arange(max_len).unsqueeze(1)
        div = torch.exp(torch.arange(0, dim, 2) * (-math.log(10000.0) / dim))
        pe = torch.zeros(max_len, dim)
        pe[:, 0::2] = torch.sin(pos * div)
        pe[:, 1::2] = torch.cos(pos * div[: pe[:, 1::2].shape[1]])
        self.register_buffer("pe", pe.unsqueeze(0))

    def forward(self, x: Tensor) -> Tensor:
        return x + self.pe[:, : x.size(1)]


def _rff(x: Tensor, W: Tensor, b: Tensor) -> Tensor:
    proj = torch.einsum("bhmd,hdr->bhmr", x, W) + b.unsqueeze(0).unsqueeze(2)
    return torch.cat([torch.cos(proj), torch.sin(proj)], dim=-1) / math.sqrt(
        proj.size(-1)
    )


class FreqLinearAttention(nn.Module):
    def __init__(self, dim: int, heads: int = 8, rank: int = 64):
        super().__init__()
        if dim % heads != 0:
            raise ValueError("hidden dimension must be divisible by n_heads")
        self.heads = heads
        self.head_dim = dim // heads
        self.rank = rank
        self.q = nn.Linear(dim, dim)
        self.k = nn.Linear(dim, dim)
        self.v = nn.Linear(dim, dim)
        self.proj = nn.Linear(dim, dim)
        scale = 1.0 / math.sqrt(self.head_dim)
        self.W = nn.Parameter(torch.randn(heads, self.head_dim, rank // 2) * scale)
        self.b = nn.Parameter(2 * math.pi * torch.rand(heads, rank // 2))

    def forward(self, x: Tensor) -> Tensor:
        batch_size, num_vars, dim = x.shape
        fx = torch.fft.rfft(x, norm="forward")
        fx = torch.view_as_real(fx)
        fx = torch.cat((fx[..., 0], -fx[..., 1]), dim=-1)[..., :dim]

        def split(tensor: Tensor) -> Tensor:
            return tensor.view(batch_size, num_vars, self.heads, self.head_dim).transpose(1, 2)

        q, k, v = map(split, (self.q(fx), self.k(fx), self.v(fx)))
        phi_q, phi_k = _rff(q, self.W, self.b), _rff(k, self.W, self.b)
        k_sum = phi_k.sum(2)
        kv_sum = torch.einsum("bhmr,bhmd->bhrd", phi_k, v)
        denom = torch.einsum("bhmr,bhr->bhm", phi_q, k_sum).unsqueeze(-1) + 1e-6
        out = torch.einsum("bhmr,bhrd->bhmd", phi_q, kv_sum) / denom
        out = out.transpose(1, 2).reshape(batch_size, num_vars, dim)
        out = self.proj(out)
        real, imag = torch.chunk(out, 2, dim=-1)
        return torch.fft.irfft(torch.complex(real, -imag), n=dim, norm="forward")


class FreqBlock(nn.Module):
    def __init__(self, dim: int, heads: int = 8, mlp_ratio: float = 4.0, rank: int = 64):
        super().__init__()
        self.norm1 = nn.LayerNorm(dim)
        self.attn = FreqLinearAttention(dim, heads, rank)
        self.norm2 = nn.LayerNorm(dim)
        hidden = int(dim * mlp_ratio)
        self.mlp = nn.Sequential(nn.Linear(dim, hidden), nn.ReLU(True), nn.Linear(hidden, dim))

    def forward(self, x: Tensor) -> Tensor:
        x = x + self.attn(self.norm1(x))
        return x + self.mlp(self.norm2(x))


class KAFNetEncoder(nn.Module):
    def __init__(
        self,
        num_sensors: int,
        hidden_dim: int,
        kernel_count: int,
        time_dim: int,
        n_layers: int,
        n_heads: int,
        preconv_dim: int,
        context_dim: int = 0,
    ):
        super().__init__()
        self.num_sensors = num_sensors
        self.hidden_dim = hidden_dim
        self.kernel_count = kernel_count
        self.time_dim = time_dim

        self.intra = TTKMN(kernel_count)
        self.te_proj1d = nn.Linear(time_dim, 1)
        self.feat_proj = nn.Linear(kernel_count + 1, hidden_dim)
        self.pos = PositionalEncoding(hidden_dim, max_len=num_sensors)
        self.blocks = nn.ModuleList(
            [FreqBlock(hidden_dim, heads=n_heads, mlp_ratio=4.0, rank=64) for _ in range(n_layers)]
        )
        self.var_agg = nn.Linear(hidden_dim, hidden_dim)
        self.pre_conv = nn.Sequential(
            nn.Conv1d(1, preconv_dim, kernel_size=3, padding=1),
            nn.ReLU(True),
            nn.Conv1d(preconv_dim, 1, kernel_size=1),
        )
        self.te_scale = nn.Linear(1, 1)
        self.te_per_sin = nn.Linear(1, (time_dim - 1) // 2)
        self.te_per_cos = nn.Linear(1, time_dim - 1 - ((time_dim - 1) // 2))
        self.context_proj = (
            nn.Linear(context_dim, 2 * hidden_dim) if context_dim and context_dim > 0 else None
        )
        if self.context_proj is not None:
            nn.init.zeros_(self.context_proj.weight)
            nn.init.zeros_(self.context_proj.bias)

    def _time_embedding(self, t: Tensor) -> Tensor:
        return torch.cat(
            [self.te_scale(t), torch.sin(self.te_per_sin(t)), torch.cos(self.te_per_cos(t))],
            dim=-1,
        )

    def encode(self, X: Tensor, T_obs: Tensor, M_obs: Tensor, context: Tensor = None) -> Tensor:
        batch_size, history_len, num_sensors = X.shape
        if num_sensors != self.num_sensors:
            raise ValueError(f"Expected {self.num_sensors} sensors, got {num_sensors}")

        T = T_obs[..., None].repeat(1, 1, num_sensors) if T_obs.dim() == 2 else T_obs
        Xf = X.transpose(1, 2).reshape(-1, 1, history_len)
        Xf = self.pre_conv(Xf).transpose(1, 2)
        Tf = T.permute(0, 2, 1).reshape(-1, history_len, 1)
        Mf = M_obs.permute(0, 2, 1).reshape(-1, history_len, 1)

        t_min = Tf.min(dim=1, keepdim=True)[0]
        t_max = Tf.max(dim=1, keepdim=True)[0]
        Tf_normalized = (Tf - t_min) / (t_max - t_min + 1e-8)
        Xf_enhanced = Xf + self.te_proj1d(self._time_embedding(Tf))

        z = self.intra(Tf_normalized, Xf_enhanced, Mf)
        z = self.feat_proj(z).view(batch_size, num_sensors, self.hidden_dim)
        z = self.pos(z)
        for block in self.blocks:
            z = block(z)
        z = self.var_agg(z)

        if self.context_proj is not None and context is not None:
            gamma, beta = self.context_proj(context).chunk(2, dim=-1)
            z = z * (1.0 + gamma[:, None, :]) + beta[:, None, :]
        return z

    def forward(self, X: Tensor, T_obs: Tensor, M_obs: Tensor, context: Tensor = None) -> Tensor:
        return self.encode(X, T_obs, M_obs, context)


def _masked_patch_stats(values: Tensor, times: Tensor, mask: Tensor) -> Tensor:
    valid_count = mask.sum(dim=1).clamp_min(1.0)
    masked_values = values * mask
    mean = masked_values.sum(dim=1) / valid_count
    centered = (values - mean[:, None, :]) * mask
    std = torch.sqrt((centered.pow(2).sum(dim=1) / valid_count).clamp_min(1e-8)).clamp_max(1e6)

    t_mean = (times * mask).sum(dim=1) / valid_count
    t_centered = (times - t_mean[:, None, :]) * mask
    slope_num = (t_centered * centered).sum(dim=1)
    slope_den = t_centered.pow(2).sum(dim=1).clamp_min(1e-6)
    slope = slope_num / slope_den

    missing_ratio = 1.0 - mask.mean(dim=1)
    has_value = (mask.sum(dim=1) > 0).float()
    time_span = (times.max(dim=1).values - times.min(dim=1).values) * has_value
    return torch.stack([mean, std, slope, missing_ratio, time_span], dim=-1)


class MultiScaleKAFEncoder(KAFNetEncoder):
    def __init__(
        self,
        num_sensors: int,
        hidden_dim: int,
        kernel_count: int,
        time_dim: int,
        n_layers: int,
        n_heads: int,
        preconv_dim: int,
        patch_lens=(12, 24, 48),
        context_dim: int = 0,
    ):
        super().__init__(
            num_sensors=num_sensors,
            hidden_dim=hidden_dim,
            kernel_count=kernel_count,
            time_dim=time_dim,
            n_layers=n_layers,
            n_heads=n_heads,
            preconv_dim=preconv_dim,
            context_dim=context_dim,
        )
        self.patch_lens = tuple(int(length) for length in patch_lens)
        if not self.patch_lens or any(length <= 0 for length in self.patch_lens):
            raise ValueError("patch_lens must contain at least one positive length")

        self.local_intra = TTKMN(kernel_count)
        self.local_feat_proj = nn.Linear(kernel_count + 1, hidden_dim)
        self.stat_proj = nn.Sequential(
            nn.Linear(5, hidden_dim),
            nn.ReLU(True),
            nn.Linear(hidden_dim, hidden_dim),
        )
        self.local_norm = nn.LayerNorm(hidden_dim)
        self.local_score = nn.Linear(hidden_dim, 1)
        self.merge_gate = nn.Sequential(
            nn.Linear(hidden_dim * 2, hidden_dim),
            nn.ReLU(True),
            nn.Linear(hidden_dim, hidden_dim),
            nn.Sigmoid(),
        )

    def _expand_times(self, T_obs: Tensor, num_sensors: int) -> Tensor:
        if T_obs.dim() == 2:
            return T_obs[..., None].expand(-1, -1, num_sensors)
        if T_obs.dim() == 3:
            if T_obs.shape[-1] != num_sensors:
                raise ValueError(f"Expected {num_sensors} time channels, got {T_obs.shape[-1]}")
            return T_obs
        raise ValueError("T_obs must have shape (B, L) or (B, L, N)")

    def _kaf_pool(
        self,
        values: Tensor,
        times: Tensor,
        mask: Tensor,
        intra: TTKMN,
        feat_proj: nn.Module,
    ) -> Tensor:
        batch_size, history_len, num_sensors = values.shape
        Xf = values.transpose(1, 2).reshape(-1, 1, history_len)
        Xf = self.pre_conv(Xf).transpose(1, 2)
        Tf = times.permute(0, 2, 1).reshape(-1, history_len, 1)
        Mf = mask.permute(0, 2, 1).reshape(-1, history_len, 1)

        t_min = Tf.min(dim=1, keepdim=True)[0]
        t_max = Tf.max(dim=1, keepdim=True)[0]
        Tf_normalized = (Tf - t_min) / (t_max - t_min + 1e-8)
        Xf_enhanced = Xf + self.te_proj1d(self._time_embedding(Tf))

        z = intra(Tf_normalized, Xf_enhanced, Mf)
        return feat_proj(z).view(batch_size, num_sensors, self.hidden_dim)

    def _local_representation(self, X: Tensor, T: Tensor, M_obs: Tensor) -> Tensor:
        _, history_len, _ = X.shape
        tokens = []
        for patch_len in self.patch_lens:
            effective_len = min(patch_len, history_len)
            for start in range(0, history_len, effective_len):
                end = min(start + effective_len, history_len)
                patch_x = X[:, start:end, :]
                patch_t = T[:, start:end, :]
                patch_m = M_obs[:, start:end, :]
                local_kaf = self._kaf_pool(
                    patch_x,
                    patch_t,
                    patch_m,
                    self.local_intra,
                    self.local_feat_proj,
                )
                stats = self.stat_proj(_masked_patch_stats(patch_x, patch_t, patch_m))
                tokens.append(self.local_norm(local_kaf + stats))

        stacked = torch.stack(tokens, dim=2)
        scores = self.local_score(stacked).squeeze(-1)
        weights = torch.softmax(scores, dim=-1)
        return (stacked * weights.unsqueeze(-1)).sum(dim=2)

    def encode(self, X: Tensor, T_obs: Tensor, M_obs: Tensor, context: Tensor = None) -> Tensor:
        batch_size, _, num_sensors = X.shape
        if num_sensors != self.num_sensors:
            raise ValueError(f"Expected {self.num_sensors} sensors, got {num_sensors}")

        T = self._expand_times(T_obs, num_sensors)
        z_global = self._kaf_pool(X, T, M_obs, self.intra, self.feat_proj)
        z_local = self._local_representation(X, T, M_obs)
        gate = self.merge_gate(torch.cat([z_global, z_local], dim=-1))
        z = gate * z_global + (1.0 - gate) * z_local

        z = self.pos(z)
        for block in self.blocks:
            z = block(z)
        z = self.var_agg(z)

        if self.context_proj is not None and context is not None:
            gamma, beta = self.context_proj(context).chunk(2, dim=-1)
            z = z * (1.0 + gamma[:, None, :]) + beta[:, None, :]
        return z


class HierarchicalMissingnessKAFEncoder(nn.Module):
    """Scheme B encoder wrapper with mask-safe values and patch identities."""

    def __init__(
        self,
        num_sensors: int,
        hidden_dim: int,
        kernel_count: int,
        time_dim: int,
        n_layers: int,
        n_heads: int,
        preconv_dim: int,
        patch_lens=(12, 24, 48),
        context_dim: int = 0,
        freshness_tau: float = 24.0,
    ):
        super().__init__()
        from .missingness_features import MissingnessFeatures

        self.num_sensors = int(num_sensors)
        self.hidden_dim = int(hidden_dim)
        self.patch_lens = tuple(int(value) for value in patch_lens)
        self.base = MultiScaleKAFEncoder(
            num_sensors=num_sensors,
            hidden_dim=hidden_dim,
            kernel_count=kernel_count,
            time_dim=time_dim,
            n_layers=n_layers,
            n_heads=n_heads,
            preconv_dim=preconv_dim,
            patch_lens=self.patch_lens,
            context_dim=context_dim,
        )
        padding = 1
        self.mask_value_conv = nn.Conv1d(1, preconv_dim, kernel_size=3, padding=padding, bias=False)
        self.mask_output_conv = nn.Conv1d(preconv_dim, 1, kernel_size=1)
        self.register_buffer("mask_support_kernel", torch.ones(1, 1, 3))
        self.mask_conv_eps = 1e-6
        self.missingness = MissingnessFeatures(freshness_tau=freshness_tau)
        self.missing_proj = nn.Sequential(
            nn.Linear(5, hidden_dim), nn.ReLU(True), nn.Linear(hidden_dim, hidden_dim)
        )
        self.position_embedding = nn.Embedding(512, hidden_dim)
        self.scale_embedding = nn.Embedding(max(1, len(self.patch_lens)), hidden_dim)
        self.recency_proj = nn.Linear(1, hidden_dim)
        self.patch_score = nn.Linear(hidden_dim, 1)
        self.patch_norm = nn.LayerNorm(hidden_dim)
        self.merge_gate = nn.Sequential(
            nn.Linear(hidden_dim * 2, hidden_dim), nn.ReLU(True),
            nn.Linear(hidden_dim, hidden_dim), nn.Sigmoid(),
        )

    def forward(self, X: Tensor, T_obs: Tensor, M_obs: Tensor, context: Tensor = None) -> Tensor:
        if X.dim() != 3 or M_obs.shape != X.shape:
            raise ValueError("X and M_obs must both have shape [B,L,N]")
        features = self.missingness(T_obs, M_obs)
        # Values outside the observation mask cannot affect either convolution
        # or the KAF pooling path.
        values_flat = (X * M_obs).transpose(1, 2).reshape(-1, 1, X.shape[1])
        mask_flat = M_obs.transpose(1, 2).reshape(-1, 1, X.shape[1])
        numerator = self.mask_output_conv(self.mask_value_conv(values_flat))
        support = F.conv1d(mask_flat, self.mask_support_kernel, padding=1)
        # The support count is an integer-valued mask convolution; using one
        # as the lower bound keeps empty neighborhoods finite without creating
        # huge intermediate values that can poison gradients before masking.
        normalized_flat = numerator / support.clamp_min(1.0)
        normalized_flat = torch.where(support > 0, normalized_flat, torch.zeros_like(normalized_flat))
        normalized_values = normalized_flat.reshape(X.shape[0], X.shape[2], X.shape[1]).transpose(1, 2)
        observed_values = normalized_values * M_obs
        z_global = self.base(observed_values, T_obs, M_obs, context)

        count = M_obs.sum(dim=1).clamp_min(1.0)
        mean = observed_values.sum(dim=1) / count
        centered = (observed_values - mean.unsqueeze(1)) * M_obs
        std = torch.sqrt((centered.pow(2).sum(dim=1) / count).clamp_min(1e-8)).clamp_max(1e6)
        stats = torch.stack(
            [mean, std, features.delta_t[:, -1], features.freshness[:, -1], features.observed_ratio[:, -1]],
            dim=-1,
        )
        z_stats = self.missing_proj(stats)

        tokens = []
        valid_tokens = []
        history_len = X.shape[1]
        for scale_index, patch_len in enumerate(self.patch_lens):
            effective_len = min(max(1, patch_len), history_len)
            for start in range(0, history_len, effective_len):
                end = min(start + effective_len, history_len)
                patch_mask = M_obs[:, start:end]
                patch_values = observed_values[:, start:end]
                patch_count = patch_mask.sum(dim=1).clamp_min(1.0)
                patch_mean = patch_values.sum(dim=1) / patch_count
                patch_age = features.delta_t[:, end - 1].mean(dim=-1, keepdim=True)
                token = z_stats + patch_mean.unsqueeze(-1) * 0.0
                token = token + self.recency_proj(patch_age / float(max(1, patch_len))).unsqueeze(1)
                position = self.position_embedding(
                    torch.full((X.shape[0],), min(start, 511), device=X.device, dtype=torch.long)
                ).unsqueeze(1)
                scale = self.scale_embedding.weight[scale_index].view(1, 1, -1)
                tokens.append(self.patch_norm(token + position + scale))
                valid_tokens.append((patch_mask.sum(dim=(1, 2)) > 0).to(X.dtype))

        stacked = torch.stack(tokens, dim=1)
        valid = torch.stack(valid_tokens, dim=1)
        logits = self.patch_score(stacked).squeeze(-1).masked_fill(
            valid.unsqueeze(-1) <= 0, torch.finfo(stacked.dtype).min
        )
        weights = torch.softmax(logits, dim=1) * valid.unsqueeze(-1)
        z_local = (stacked * weights.unsqueeze(-1)).sum(dim=1)
        z_local = z_local / weights.sum(dim=1).unsqueeze(-1).clamp_min(1e-6)
        gate = self.merge_gate(torch.cat([z_global, z_local], dim=-1))
        return gate * z_global + (1.0 - gate) * z_local
