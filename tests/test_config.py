import json

import pytest

from focus_guard.config import Config, ConfigError, load_config, save_config


def test_missing_file_creates_defaults(tmp_path):
    path = tmp_path / "config.json"
    cfg = load_config(path)
    assert cfg == Config()
    assert path.exists()
    assert json.loads(path.read_text())["activation_delay_s"] == 2.0


def test_roundtrip_with_calibration(tmp_path):
    path = tmp_path / "config.json"
    cfg = Config(
        exit_margin=0.2,
        calibration={
            "top_left": [0.6, 0.4, -10, 5],
            "top_right": [0.4, 0.4, 10, 5],
            "bottom_right": [0.4, 0.46, 10, -5],
            "bottom_left": [0.6, 0.46, -10, -5],
        },
    )
    save_config(cfg, path)
    assert load_config(path) == cfg
    assert not path.with_suffix(".json.tmp").exists()


def test_unknown_keys_are_ignored(tmp_path):
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"exit_margin": 0.3, "obsolete": 1}))
    assert load_config(path).exit_margin == 0.3


@pytest.mark.parametrize(
    "data",
    [
        {"exit_margin": 0.0, "reentry_margin": 0.1},
        {"activation_delay_s": -1},
        {"smoothing_alpha": 0},
        {"music_volume": 2},
        {"calibration": {"top_left": [0, 0, 0, 0]}},
    ],
)
def test_invalid_values_rejected(tmp_path, data):
    path = tmp_path / "config.json"
    path.write_text(json.dumps(data))
    with pytest.raises(ConfigError):
        load_config(path)


def test_non_object_rejected(tmp_path):
    path = tmp_path / "config.json"
    path.write_text("[]")
    with pytest.raises(ConfigError):
        load_config(path)


def test_resolve_path(tmp_path):
    cfg = Config()
    assert cfg.resolve_path("assets/images", tmp_path) == tmp_path / "assets/images"
    assert cfg.resolve_path(str(tmp_path)) == tmp_path
