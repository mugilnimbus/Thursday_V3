"""The requirements check's wording and rules, and stopping model servers an agent left behind."""

import pathlib

from thursday_launcher.application.checkup import Facts, Level, dashboard_stale, findings, node_major, report
from thursday_launcher.application.strays import stop_all, stop_for_service

READY = Facts(
    env_file=True,
    service_token=True,
    node_version="v24.1.0",
    npm=True,
    dashboard_built=True,
    dashboard_stale=False,
    llamacpp="b9 (cuda-12.4)",
    own_llamacpp_dir="",
    own_llamacpp_ok=False,
    nvidia=True,
    credential_store=True,
    tailscale=True,
    tailscale_serving=True,
    agents=[("main", "lmstudio", True), ("voice", "llamacpp", True)],
    ports_taken=[],
    speech_models=True,
)


def changed(**fields: object) -> dict[str, tuple[Level, str, str]]:
    facts = Facts(**{**{name: getattr(READY, name) for name in READY.__slots__}, **fields})  # type: ignore[arg-type]
    return {item.name: (item.level, item.detail, item.fix) for item in findings(facts)}


def test_a_ready_pc_has_nothing_missing() -> None:
    found = findings(READY)
    assert all(item.level is Level.OK for item in found)
    said: list[str] = []
    assert report(found, said.append) == 0
    assert said[-1] == "Everything Thursday needs is here."


def test_a_fresh_pc_is_told_what_to_install_and_how() -> None:
    fresh = changed(
        env_file=False,
        service_token=False,
        node_version=None,
        npm=False,
        dashboard_built=False,
        llamacpp=None,
        nvidia=False,
        tailscale=False,
        tailscale_serving=None,
        agents=None,
        speech_models=False,
    )
    assert fresh[".env settings file"] == (Level.MISSING, "not created yet", "Run `uv run thursday setup`.")
    level, detail, fix = fresh["Dashboard"]
    assert (
        level is Level.MISSING
        and "Node.js is not installed" in detail
        and "nodejs.org" in fix
        and "npm run build" in fix
    )
    assert fresh["Built-in llama.cpp"][0] is Level.OPTIONAL and "thursday setup" in fresh["Built-in llama.cpp"][2]
    assert fresh["Tailscale (for the phone)"][0] is Level.OPTIONAL
    assert fresh["Speech models"][0] is Level.OPTIONAL and "by themselves" in fresh["Speech models"][2]
    assert not any(name.endswith("agent's model") for name in fresh), "agents are only reported while Thursday runs"


def test_the_dashboard_says_which_step_is_missing() -> None:
    assert changed(dashboard_built=False)["Dashboard"][1] == "not built"
    assert "too old" in changed(dashboard_built=False, node_version="v18.2.0")["Dashboard"][1]
    stale = changed(dashboard_stale=True)["Dashboard"]
    assert stale[0] is Level.MISSING and "older than its source" in stale[1]
    assert node_major("v24.1.0") == 24 and node_major(None) is None and node_major("weird") is None


def test_an_agent_whose_model_source_is_down_and_a_taken_port_are_named() -> None:
    found = changed(agents=[("main", "lmstudio", False), ("voice", "llamacpp", True)], ports_taken=[8700, 8711])
    assert (
        found["Main agent's model"][0] is Level.MISSING and "LM Studio is not ready" in found["Main agent's model"][1]
    )
    assert found["Voice agent's model"][0] is Level.OK
    assert found["Ports"] == (
        Level.MISSING,
        "in use by another program: 8700, 8711",
        "Close that program, or change the port in .env.",
    )
    assert "not published" in changed(tailscale_serving=False)["Tailscale (for the phone)"][1]
    own = changed(own_llamacpp_dir="D:/llama", own_llamacpp_ok=False)["Built-in llama.cpp (your own build)"]
    assert own[0] is Level.OPTIONAL and "no llama-server found" in own[1]


def test_the_report_can_show_only_what_blocks(tmp_path: pathlib.Path) -> None:
    said: list[str] = []
    facts = Facts(
        **{**{name: getattr(READY, name) for name in READY.__slots__}, "dashboard_built": False, "nvidia": False}
    )  # type: ignore[arg-type]
    assert report(findings(facts), said.append, only_problems=True) == 1
    assert len(said) == 2 and "MISSING" in said[0] and "Dashboard" in said[0] and "->" in said[1]

    dist, source = tmp_path / "dist", tmp_path / "src"
    dist.mkdir()
    source.mkdir()
    assert not dashboard_stale(dist, source), "nothing built yet is not 'stale'"
    (dist / "index.html").write_text("built")
    (source / "App.svelte").write_text("newer")
    import os

    os.utime(dist / "index.html", (1000, 1000))
    assert dashboard_stale(dist, source)


class FakeStopper:
    def __init__(self, llama: set[int], elsewhere: list[int] | None = None) -> None:
        self.llama = set(llama)
        self.elsewhere = elsewhere or []
        self.stopped: list[int] = []

    def stop_llama(self, pid: int, folders: object) -> bool:
        if pid not in self.llama:
            return False  # not running any more, or the number now belongs to another program
        self.llama.discard(pid)
        self.stopped.append(pid)
        return True

    def llama_under(self, folders: object) -> list[int]:
        return [pid for pid in self.elsewhere if pid in self.llama]


def test_before_an_agent_starts_only_its_own_leftover_server_is_stopped(tmp_path: pathlib.Path) -> None:
    (tmp_path / "llama-voice.pid").write_text("111")
    (tmp_path / "llama-main.pid").write_text("222")
    stopper = FakeStopper({111, 222})
    assert stop_for_service(tmp_path, stopper, "voice_agent", [tmp_path]) == 1
    assert stopper.stopped == [111] and not (tmp_path / "llama-voice.pid").exists()
    assert (tmp_path / "llama-main.pid").exists(), "the main agent's server belongs to a running agent"
    assert stop_for_service(tmp_path, stopper, "gateway", [tmp_path]) == 0
    assert stop_for_service(tmp_path, stopper, "voice_agent", [tmp_path]) == 0, "nothing recorded, nothing to do"


def test_a_stale_record_never_stops_another_program(tmp_path: pathlib.Path) -> None:
    (tmp_path / "llama-main.pid").write_text("333")  # the number now belongs to something else
    (tmp_path / "llama-voice.pid").write_text("not a number")
    stopper = FakeStopper(set())
    assert stop_all(tmp_path, stopper, []) == 0 and stopper.stopped == []
    assert not (tmp_path / "llama-main.pid").exists()


def test_after_everything_is_stopped_recorded_and_unrecorded_servers_go(tmp_path: pathlib.Path) -> None:
    (tmp_path / "llama-main.pid").write_text("222")
    stopper = FakeStopper({222, 444}, elsewhere=[222, 444])  # 444 was started from Thursday's folder, no record
    assert stop_all(tmp_path, stopper, [tmp_path]) == 2
    assert sorted(stopper.stopped) == [222, 444]
