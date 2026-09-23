from dataclasses import dataclass
from typing import Iterable, List, Optional

import torch
from torch import Tensor


@dataclass
class IndustrialBatch:
    X_obs: Tensor
    T_obs: Tensor
    M_obs: Tensor
    T_q: Tensor
    Y_q: Tensor
    M_q: Tensor
    context: Tensor
    y_flat: Tensor
    mq_flat: Tensor
    query_channel_ids: Tensor
    rul: Tensor
    unit_id: Tensor
    window_id: Optional[List[str]] = None

    def to(self, device: torch.device) -> "IndustrialBatch":
        return IndustrialBatch(
            X_obs=self.X_obs.to(device),
            T_obs=self.T_obs.to(device),
            M_obs=self.M_obs.to(device),
            T_q=self.T_q.to(device),
            Y_q=self.Y_q.to(device),
            M_q=self.M_q.to(device),
            context=self.context.to(device),
            y_flat=self.y_flat.to(device),
            mq_flat=self.mq_flat.to(device),
            query_channel_ids=self.query_channel_ids.to(device),
            rul=self.rul.to(device),
            unit_id=self.unit_id.to(device),
            window_id=self.window_id,
        )


class IndustrialCollator:
    """Stack fixed-length industrial windows and flatten query targets."""

    def __call__(self, samples: Iterable[object]) -> IndustrialBatch:
        batch = list(samples)
        if not batch:
            raise ValueError("IndustrialCollator received an empty batch")

        X_obs = torch.stack([sample.X_obs for sample in batch])
        T_obs = torch.stack([sample.T_obs for sample in batch])
        M_obs = torch.stack([sample.M_obs for sample in batch])
        T_q = torch.stack([sample.T_q for sample in batch])
        Y_q = torch.stack([sample.Y_q for sample in batch])
        M_q = torch.stack([sample.M_q for sample in batch])
        context = torch.stack([sample.context for sample in batch])
        rul = torch.tensor([float(sample.rul) for sample in batch], dtype=torch.float32)
        unit_id = torch.tensor([int(sample.unit_id) for sample in batch], dtype=torch.long)
        raw_window_ids = [getattr(sample, "window_id", None) for sample in batch]
        window_id = (
            [str(value) for value in raw_window_ids]
            if all(value not in (None, "") for value in raw_window_ids)
            else None
        )

        batch_size, pred_len, num_sensors = Y_q.shape
        y_flat = Y_q.reshape(batch_size, pred_len * num_sensors)
        mq_flat = M_q.reshape(batch_size, pred_len * num_sensors)
        query_channel_ids = torch.arange(num_sensors, dtype=torch.long).repeat(pred_len)

        return IndustrialBatch(
            X_obs=X_obs,
            T_obs=T_obs,
            M_obs=M_obs,
            T_q=T_q,
            Y_q=Y_q,
            M_q=M_q,
            context=context,
            y_flat=y_flat,
            mq_flat=mq_flat,
            query_channel_ids=query_channel_ids,
            rul=rul,
            unit_id=unit_id,
            window_id=window_id,
        )
