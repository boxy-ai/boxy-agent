from __future__ import annotations

from boxy_agent.main_agent.config import load_main_agent_config


def test_main_agent_config_defaults(monkeypatch) -> None:  # noqa: ANN001
    monkeypatch.delenv("BOXY_MAIN_AGENT_MODEL", raising=False)
    monkeypatch.delenv("BOXY_MAIN_AGENT_MAX_ITERATIONS", raising=False)
    monkeypatch.delenv("BOXY_MAIN_AGENT_TOP_K", raising=False)

    config = load_main_agent_config()

    assert config.model == "anthropic/claude-opus-4.6"
    assert config.max_iterations == 20
    assert config.top_k == 12


def test_main_agent_config_applies_env_and_clamps_top_k(monkeypatch) -> None:  # noqa: ANN001
    monkeypatch.setenv("BOXY_MAIN_AGENT_MODEL", " custom-model ")
    monkeypatch.setenv("BOXY_MAIN_AGENT_MAX_ITERATIONS", "15")
    monkeypatch.setenv("BOXY_MAIN_AGENT_TOP_K", "100")

    config = load_main_agent_config()

    assert config.model == "custom-model"
    assert config.max_iterations == 15
    assert config.top_k == 20
