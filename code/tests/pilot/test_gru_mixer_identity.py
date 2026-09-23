from pathlib import Path

import pytest

torch = pytest.importorskip("torch")

from kaf_profiti.experiments.pilot_runner import PilotRunner, build_model, load_matrix


def _runner(matrix_name, tmp_path):
    root = Path(__file__).resolve().parents[3]
    return PilotRunner(
        [load_matrix(root / "configs" / "pilot" / "metropt3" / matrix_name)],
        result_root=tmp_path / "result",
        data_root=root / "dataset",
        device="cpu",
        profile="metropt3",
    )


def test_g1_g4_variant_identity_is_unique_from_a1_f1_f3(tmp_path):
    root = Path(__file__).resolve().parents[3]
    names = [
        "scheme_b_point_a1_matrix.yaml",
        "scheme_b_point_f1_matrix.yaml",
        "scheme_b_point_f2_matrix.yaml",
        "scheme_b_point_f3_matrix.yaml",
        "scheme_b_point_g1_gru_mixer_h16_matrix.yaml",
        "scheme_b_point_g2_gru_mixer_h32_matrix.yaml",
        "scheme_b_point_g3_gru_mixer_no_ffill_matrix.yaml",
        "scheme_b_point_g4_gru_mixer_direct_residual_matrix.yaml",
    ]
    specs = [
        PilotRunner(
            [load_matrix(root / "configs" / "pilot" / "metropt3" / name)],
            result_root=tmp_path / name,
            data_root=root / "dataset",
            device="cpu",
            profile="metropt3",
        ).expand()[0]
        for name in names
    ]
    assert len({spec.variant_id for spec in specs}) == len(specs)
    assert len({spec.key for spec in specs}) == len(specs)
    assert {spec.cross_variable_mode for spec in specs[-4:]} == {"gru_mixer"}


@pytest.mark.parametrize(
    "matrix_name, hidden, use_forward_fill, direct_residual",
    [
        ("scheme_b_point_g1_gru_mixer_h16_matrix.yaml", 16, True, False),
        ("scheme_b_point_g2_gru_mixer_h32_matrix.yaml", 32, True, False),
        ("scheme_b_point_g3_gru_mixer_no_ffill_matrix.yaml", 32, False, False),
        ("scheme_b_point_g4_gru_mixer_direct_residual_matrix.yaml", 32, True, True),
    ],
)
def test_gru_variant_reaches_model_recipe(tmp_path, matrix_name, hidden, use_forward_fill, direct_residual):
    runner = _runner(matrix_name, tmp_path)
    spec = runner.expand()[0]
    model = build_model(spec, num_sensors=3, context_dim=2, options={}, device="cpu")
    assert model.config.cross_variable_mode == "gru_mixer"
    assert model.config.gru_hidden == hidden
    assert model.config.gru_use_forward_fill is use_forward_fill
    assert model.config.gru_direct_residual is direct_residual
    assert model.config.to_dict()["gru_hidden"] == hidden
