"""Global sum-based metric accumulation (CH2.5-P01-T05).

Evaluators convert batch-level values into (sum, count) pairs and accumulate
them here, so every reported metric is a global ratio over unified sums:
MAE/RMSE from the absolute/squared error sums over the valid-count, NLL/CRPS
from log-score/CRPS sums over their own valid counts, and PICP/MPIW from
coverage counts and width sums. Results are therefore invariant to DataLoader
batch sizes and trailing small batches, and RMSE can never degrade into an
average of per-batch RMSE values.

Point-only evaluation uses :meth:`point_only_result`, which forces the
probabilistic metrics to ``null`` with a ``not_applicable`` marker instead of
fabricating distributions for point forecasts.
"""

import math
from dataclasses import dataclass, field
from typing import Dict

import torch
from torch import Tensor


@dataclass
class _IntervalChannel:
    covered_count: float = 0.0
    width_sum: float = 0.0
    count: float = 0.0


@dataclass
class GlobalMetricAccumulator:
    """Accumulate metric sums globally across batches of any size."""

    abs_error_sum: float = 0.0
    sq_error_sum: float = 0.0
    valid_count: float = 0.0
    nll_sum: float = 0.0
    nll_count: float = 0.0
    crps_sum: float = 0.0
    crps_count: float = 0.0
    _intervals: Dict[str, _IntervalChannel] = field(default_factory=dict)

    def update_point(self, y: Tensor, mean: Tensor, mask: Tensor) -> None:
        """Accumulate absolute/squared error sums over valid positions.

        Valid positions require ``mask > 0`` and finite target and prediction;
        masked and non-finite positions are excluded from every sum.
        """
        valid = (mask > 0) & y.isfinite() & mean.isfinite()
        # torch.where, not multiplication: nan * 0 is still nan.
        diff = torch.where(valid, mean - y, torch.zeros_like(mean))
        self.abs_error_sum += float(diff.abs().sum())
        self.sq_error_sum += float(diff.pow(2).sum())
        self.valid_count += float(valid.sum())

    def update_nll(self, value_sum: float, count: float) -> None:
        """Accumulate a batch log-score sum and its valid-position count."""
        if count <= 0:
            raise ValueError("update_nll requires a positive count")
        self.nll_sum += float(value_sum)
        self.nll_count += float(count)

    def update_crps(self, value_sum: float, count: float) -> None:
        """Accumulate a batch CRPS sum and its valid-position count."""
        if count <= 0:
            raise ValueError("update_crps requires a positive count")
        self.crps_sum += float(value_sum)
        self.crps_count += float(count)

    def update_interval_sums(
        self, name: str, covered_count: float, width_sum: float, count: float
    ) -> None:
        """Accumulate raw coverage count / width sums for an interval channel."""
        if count <= 0:
            raise ValueError("update_interval_sums requires a positive count")
        channel = self._intervals.setdefault(name, _IntervalChannel())
        channel.covered_count += float(covered_count)
        channel.width_sum += float(width_sum)
        channel.count += float(count)

    def update_interval_means(
        self, name: str, picp: float, mpiw: float, count: float
    ) -> None:
        """Accumulate a batch that only exposes micro-mean PICP/MPIW plus count.

        ``picp``/``mpiw`` must be batch-level ratios whose denominator is
        exactly ``count`` (the mask valid positions), so multiplying back by
        ``count`` recovers the exact sums.
        """
        self.update_interval_sums(name, float(picp) * count, float(mpiw) * count, count)

    def _channel_metrics(self, name: str):
        channel = self._intervals.get(name)
        if channel is None or channel.count <= 0:
            return None, None
        return channel.covered_count / channel.count, channel.width_sum / channel.count

    def result(self) -> Dict[str, object]:
        """Compute global metrics from accumulated sums.

        Raises:
            ValueError: If no valid point position was ever accumulated.
        """
        if self.valid_count <= 0:
            raise ValueError("no valid point positions were accumulated")
        picp, mpiw = self._channel_metrics("main")
        result: Dict[str, object] = {
            "mae": self.abs_error_sum / self.valid_count,
            "rmse": math.sqrt(self.sq_error_sum / self.valid_count),
            "valid_count": int(self.valid_count),
            "nll": self.nll_sum / self.nll_count if self.nll_count > 0 else None,
            "crps": self.crps_sum / self.crps_count if self.crps_count > 0 else None,
            "picp": picp,
            "mpiw": mpiw,
        }
        for name in sorted(self._intervals):
            if name == "main":
                continue
            name_picp, name_mpiw = self._channel_metrics(name)
            result[f"{name}_picp"] = name_picp
            result[f"{name}_mpiw"] = name_mpiw
        return result

    def point_only_result(self) -> Dict[str, object]:
        """Global point metrics with probabilistic metrics forced to null.

        Raises:
            ValueError: If any probabilistic sum was accumulated, because a
                point-only run must never emit NLL/CRPS/PICP/MPIW values.
        """
        if self.nll_count or self.crps_count or any(
            channel.count for channel in self._intervals.values()
        ):
            raise ValueError(
                "point-only result requested but probabilistic sums were accumulated"
            )
        result = self.result()
        result["probabilistic_metrics"] = "not_applicable"
        return result
