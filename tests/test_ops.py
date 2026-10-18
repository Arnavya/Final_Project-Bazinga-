"""Operational checks: readiness, structured logging, configurable state directory."""
import io
import json
import logging

import numpy as np

from engine import config, health, logs


def _point_stores(monkeypatch, path):
    monkeypatch.setattr(config, "STORES_DIR", path)
    monkeypatch.setattr(config, "VECTOR_STORE_FILE", path / "vector_store.npz")
    monkeypatch.setattr(config, "VECTOR_META_FILE", path / "vector_meta.json")
    monkeypatch.setattr(config, "GRAPH_FILE", path / "graph.json")
    monkeypatch.setattr(config, "REQUIRED_STORE_FILES",
                        (path / "vector_store.npz", path / "vector_meta.json", path / "graph.json"))


def test_health_not_ready_when_stores_missing(tmp_path, monkeypatch):
    _point_stores(monkeypatch, tmp_path)
    result = health.check()
    assert result["ready"] is False
    assert any("vector_store.npz: missing" in p for p in result["problems"])


def test_health_ready_with_valid_stores(tmp_path, monkeypatch):
    _point_stores(monkeypatch, tmp_path)
    np.savez(tmp_path / "vector_store.npz", m=np.zeros((1, 2)))
    (tmp_path / "vector_meta.json").write_text("[]")
    (tmp_path / "graph.json").write_text("{}")
    result = health.check()
    assert result["problems"] == []
    assert result["ready"] is True
    assert result["version"] == config.APP_VERSION


def test_health_flags_corrupt_json(tmp_path, monkeypatch):
    _point_stores(monkeypatch, tmp_path)
    np.savez(tmp_path / "vector_store.npz", m=np.zeros((1, 2)))
    (tmp_path / "vector_meta.json").write_text("{not json")
    (tmp_path / "graph.json").write_text("{}")
    result = health.check()
    assert result["ready"] is False
    assert any("vector_meta.json: unreadable" in p for p in result["problems"])


def test_health_cli_exit_code(tmp_path, monkeypatch, capsys):
    _point_stores(monkeypatch, tmp_path)
    assert health.main() == 1
    assert json.loads(capsys.readouterr().out)["ready"] is False


def test_json_log_line_has_event_fields():
    buf = io.StringIO()
    handler = logging.StreamHandler(buf)
    handler.setFormatter(logs.JsonFormatter())
    logger = logging.getLogger("test-json")
    logger.handlers = [handler]
    logger.propagate = False
    logs.log_event(logger, "ask.completed", latency_ms=12, grounded=True)
    line = json.loads(buf.getvalue())
    assert line["event"] == "ask.completed"
    assert line["latency_ms"] == 12
    assert line["grounded"] is True
    assert line["level"] == "INFO"
    assert "version" in line


def test_stores_dir_env_override(tmp_path, monkeypatch):
    import importlib
    monkeypatch.setenv("STORES_DIR", str(tmp_path))
    reloaded = importlib.reload(config)
    try:
        assert reloaded.STORES_DIR == tmp_path.resolve()
        assert reloaded.GRAPH_FILE == tmp_path.resolve() / "graph.json"
    finally:
        monkeypatch.delenv("STORES_DIR")
        importlib.reload(config)
