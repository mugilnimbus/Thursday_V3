from pathlib import Path

from thursday_launcher.application.setup import ensure_env


def test_creates_env_from_example_and_generates_token(tmp_path: Path) -> None:
    example = tmp_path / ".env.example"
    example.write_text("A=1\nTHURSDAY_SERVICE_TOKEN=\nB=2\n", encoding="utf-8")
    env = tmp_path / ".env"
    notes = ensure_env(env, example)
    lines = env.read_text(encoding="utf-8").splitlines()
    assert lines[0] == "A=1" and lines[2] == "B=2"
    assert lines[1].startswith("THURSDAY_SERVICE_TOKEN=") and len(lines[1]) > 50
    assert "generated a new service token" in notes


def test_existing_token_and_other_lines_are_kept(tmp_path: Path) -> None:
    env = tmp_path / ".env"
    env.write_bytes(b"# keep me\r\nTHURSDAY_SERVICE_TOKEN=abc\r\nSECRET=x\r\n")
    ensure_env(env, tmp_path / "missing.example")
    assert env.read_bytes() == b"# keep me\r\nTHURSDAY_SERVICE_TOKEN=abc\r\nSECRET=x\r\n"


def test_missing_token_line_is_appended(tmp_path: Path) -> None:
    env = tmp_path / ".env"
    env.write_text("A=1", encoding="utf-8")
    ensure_env(env, tmp_path / "missing.example")
    assert env.read_text(encoding="utf-8").startswith("A=1\nTHURSDAY_SERVICE_TOKEN=")
