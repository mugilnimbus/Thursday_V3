from pathlib import Path

from thursday_main_agent.bootstrap.main import MainAgentSettings


def test_empty_values_in_env_file_mean_default(tmp_path: Path) -> None:
    env = tmp_path / ".env"
    env.write_text("MAIN_LLM_CONTEXT_LENGTH=\nTHURSDAY_DATA_DIR=\nGATEWAY_LOCALHOST_PORT=\n", encoding="utf-8")
    settings = MainAgentSettings(_env_file=env)  # pyright: ignore[reportCallIssue]
    assert settings.main_llm_context_length is None and settings.gateway_localhost_port == 8700
