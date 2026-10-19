"""Look at this PC for the requirements check: which programs and files are here, what holds Thursday's ports."""

import contextlib
import pathlib
import shutil
import subprocess
from collections.abc import Sequence

import httpx
from thursday_runtime.secret_store import credential_store_available
from thursday_runtime.settings import CommonSettings

from thursday_launcher.application.checkup import Facts, dashboard_stale
from thursday_launcher.application.llamacpp import SERVER_NAMES, installed
from thursday_launcher.domain.supervision import ServiceSpec
from thursday_launcher.infrastructure.releases import has_nvidia

DASHBOARD = pathlib.Path("apps/dashboard")


def _output(command: Sequence[str], timeout: float = 15) -> str | None:
    """What a program prints, or None when it is not installed or fails."""
    program = shutil.which(command[0])
    if program is None:
        return None
    try:
        result = subprocess.run(  # noqa: S603 - a program found on PATH, with fixed arguments
            [program, *command[1:]], capture_output=True, text=True, timeout=timeout, check=False
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    return result.stdout.strip() if result.returncode == 0 else None


def _agents(gateway_port: int) -> list[tuple[str, str, bool]] | None:
    """Each agent's provider and whether its model source answers, from the running gateway. None when it is down."""
    found: list[tuple[str, str, bool]] = []
    try:
        with httpx.Client(timeout=5) as client:
            for agent in ("main", "voice"):
                response = client.get(f"http://127.0.0.1:{gateway_port}/v1/agents/{agent}/llm")
                if response.status_code != 200:
                    return None
                data = response.json()
                found.append((agent, str(data.get("provider")), bool(data.get("reachable"))))
    except (httpx.HTTPError, ValueError):
        return None
    return found


def _ports_taken(specs: Sequence[ServiceSpec], healthy: Sequence[bool], extra: Sequence[int]) -> list[int]:
    """Thursday's ports that something is listening on while the Thursday service there does not answer."""
    import psutil

    listening: set[int] = set()
    with contextlib.suppress(psutil.Error):
        for conn in psutil.net_connections(kind="tcp"):
            if conn.status == psutil.CONN_LISTEN and conn.laddr:
                listening.add(conn.laddr.port)
    ours_up = {spec.port for spec, up in zip(specs, healthy, strict=True) if up}
    gateway_up = any(up for spec, up in zip(specs, healthy, strict=True) if spec.name == "gateway")
    wanted = [spec.port for spec in specs] + ([] if gateway_up else list(extra))
    return sorted(port for port in wanted if port in listening and port not in ours_up)


def gather(
    settings: CommonSettings,
    env_path: pathlib.Path,
    data: pathlib.Path,
    specs: Sequence[ServiceSpec],
    healthy: Sequence[bool],
) -> Facts:
    own = settings.llamacpp_dir
    own_ok = bool(own) and any(next(pathlib.Path(own).rglob(name), None) for name in SERVER_NAMES)
    built_in = installed(data / "llamacpp")
    serving = _output(["tailscale", "serve", "status"])
    dist = DASHBOARD / "dist"
    return Facts(
        env_file=env_path.is_file(),
        service_token=bool(settings.thursday_service_token.get_secret_value()),
        node_version=_output(["node", "--version"]),
        npm=shutil.which("npm") is not None,
        dashboard_built=(dist / "index.html").is_file(),
        dashboard_stale=dashboard_stale(dist, DASHBOARD / "src"),
        llamacpp=f"{built_in['tag']} ({built_in['kind']})" if built_in else None,
        own_llamacpp_dir=own,
        own_llamacpp_ok=own_ok,
        nvidia=has_nvidia(),
        credential_store=credential_store_available(),
        tailscale=shutil.which("tailscale") is not None,
        tailscale_serving=None if serving is None else f"127.0.0.1:{settings.gateway_proxy_port}" in serving,
        agents=_agents(settings.gateway_localhost_port),
        ports_taken=_ports_taken(specs, healthy, [settings.gateway_proxy_port]),
        speech_models=(data / "services" / "speech" / "models" / "kokoro-v1.0.onnx").is_file(),
    )
