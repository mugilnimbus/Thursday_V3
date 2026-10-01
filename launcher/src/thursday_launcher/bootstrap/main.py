"""Composition root for the launcher."""

import asyncio
import pathlib
import sys
from collections.abc import Sequence

from thursday_contracts.health import ServiceName
from thursday_runtime.log_setup import configure_logging
from thursday_runtime.paths import data_root, log_dir
from thursday_runtime.serve import LOCALHOST
from thursday_runtime.settings import CommonSettings, env_file, load_common_settings

from thursday_launcher.application.setup import ensure_env
from thursday_launcher.application.supervisor import Supervisor
from thursday_launcher.domain.supervision import ServiceSpec
from thursday_launcher.infrastructure.processes import (
    HttpHealthProbe,
    MonotonicClock,
    PsutilPortKiller,
    SubprocessStarter,
)
from thursday_launcher.transport.cli import exit_with, parse, run_down, run_status, run_up
from thursday_launcher.transport.console import Console, colour_supported


def service_specs(settings: CommonSettings) -> list[ServiceSpec]:
    """The HTTP services the launcher runs. The tool server is a stdio child of the main agent."""
    return [
        ServiceSpec(ServiceName.GATEWAY, "thursday_gateway", settings.gateway_localhost_port),
        ServiceSpec(ServiceName.VOICE_AGENT, "thursday_voice_agent", settings.voice_agent_port),
        ServiceSpec(ServiceName.MAIN_AGENT, "thursday_main_agent", settings.main_agent_port),
        ServiceSpec(ServiceName.METRICS_COLLECTOR, "thursday_metrics_collector", settings.metrics_collector_port),
        ServiceSpec(ServiceName.SPEECH, "thursday_speech", settings.speech_port),
    ]


def main(argv: Sequence[str] | None = None) -> None:
    args = parse(argv)
    if args.command == "setup":
        for note in ensure_env(env_file(), pathlib.Path(".env.example")):
            print(note)
        exit_with(0)
    settings = load_common_settings()
    specs = service_specs(settings)
    if args.command == "status":
        exit_with(asyncio.run(run_status(specs)))
    root = data_root(settings.thursday_data_dir)
    root.mkdir(parents=True, exist_ok=True)
    if args.command == "down":
        exit_with(asyncio.run(run_down(specs, root, PsutilPortKiller())))
    logs = log_dir(settings.thursday_data_dir)
    configure_logging("launcher", logs, settings.log_level, console=False)  # the terminal gets the readable report
    console = Console(
        specs,
        dashboard_url=f"http://{LOCALHOST}:{settings.gateway_localhost_port}",
        proxy_port=settings.gateway_proxy_port,
        logs=logs,
        colour=colour_supported(sys.stdout),
    )
    supervisor = Supervisor(
        specs,
        SubprocessStarter(pathlib.Path.cwd(), logs),
        HttpHealthProbe(),
        MonotonicClock(),
        on_change=console.change,
    )
    exit_with(asyncio.run(run_up(supervisor, root, console)))
