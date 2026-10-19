"""Composition root for the launcher."""

import asyncio
import pathlib
import platform
import sys
from collections.abc import Sequence

from thursday_contracts.health import ServiceName
from thursday_runtime.log_setup import configure_logging
from thursday_runtime.paths import data_root, log_dir
from thursday_runtime.serve import LOCALHOST
from thursday_runtime.settings import CommonSettings, env_file, load_common_settings

from thursday_launcher.application.checkup import findings, report
from thursday_launcher.application.llamacpp import InstallError, install
from thursday_launcher.application.setup import ensure_env
from thursday_launcher.application.strays import stop_all, stop_for_service
from thursday_launcher.application.supervisor import Supervisor
from thursday_launcher.domain.supervision import ServiceSpec
from thursday_launcher.infrastructure.machine import gather
from thursday_launcher.infrastructure.processes import (
    HttpHealthProbe,
    MonotonicClock,
    PsutilPortKiller,
    SubprocessStarter,
)
from thursday_launcher.infrastructure.releases import GitHubReleases, has_nvidia
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


def ask(question: str) -> bool:
    """A yes or no from the person at the terminal. No terminal (a script) means no."""
    if not sys.stdin or not sys.stdin.isatty():
        return False
    try:
        return input(f"{question} [y/N] ").strip().lower() in ("y", "yes")
    except EOFError:
        return False


def install_llamacpp(settings: CommonSettings, *, update: bool, without_asking: bool) -> None:
    """Offer the built-in llama.cpp and download it into the data folder if wanted. It is only needed for the
    built-in provider, so the person is asked first, told what it is and how large. A failure is reported and leaves
    the rest of setup done."""
    if settings.llamacpp_dir:
        print(f"llama.cpp: using your own build in {settings.llamacpp_dir} (LLAMACPP_DIR); nothing downloaded")
        return
    source = GitHubReleases()
    try:
        install(
            source,
            data_root(settings.thursday_data_dir) / "llamacpp",
            sys.platform,
            platform.machine(),
            has_nvidia(),
            print,
            update=update,
            confirm=None
            if without_asking
            else lambda what: ask(
                "\nThursday can run models itself with a built-in llama.cpp: you only give it a folder of\n"
                ".gguf model files. It is not needed if you use LM Studio or a cloud endpoint.\n"
                f"Download {what}?"
            ),
        )
    except InstallError as exc:
        print(f"llama.cpp was not installed: {exc}")
        print("Thursday works without it (LM Studio and cloud endpoints). Run `uv run thursday setup` to try again.")
    finally:
        source.close()


def check(settings: CommonSettings, specs: Sequence[ServiceSpec], *, only_problems: bool = False) -> int:
    """Print what is here and what is missing. Returns how many things are missing."""

    async def health() -> list[bool]:
        probe = HttpHealthProbe()
        try:
            return list(await asyncio.gather(*(probe.is_healthy(spec) for spec in specs)))
        finally:
            await probe.aclose()

    facts = gather(settings, env_file(), data_root(settings.thursday_data_dir), specs, asyncio.run(health()))
    return report(findings(facts), print, only_problems=only_problems)


def main(argv: Sequence[str] | None = None) -> None:
    args = parse(argv)
    if args.command == "setup":
        for note in ensure_env(env_file(), pathlib.Path(".env.example")):
            print(note)
        settings = load_common_settings()
        if not args.skip_llamacpp:
            install_llamacpp(
                settings, update=args.update_llamacpp, without_asking=args.with_llamacpp or args.update_llamacpp
            )
        print("\nWhat Thursday needs on this PC:")
        check(settings, service_specs(settings))
        exit_with(0)
    settings = load_common_settings()
    specs = service_specs(settings)
    if args.command == "status":
        exit_with(asyncio.run(run_status(specs, HttpHealthProbe())))
    if args.command == "check":
        exit_with(1 if check(settings, specs) else 0)
    root = data_root(settings.thursday_data_dir)
    root.mkdir(parents=True, exist_ok=True)
    logs = log_dir(settings.thursday_data_dir)
    killer = PsutilPortKiller()
    llama_folders = [root / "llamacpp", *([pathlib.Path(settings.llamacpp_dir)] if settings.llamacpp_dir else [])]
    if args.command == "down":
        stop_leftovers = lambda: stop_all(logs, killer, llama_folders)  # noqa: E731 - one short callback
        exit_with(asyncio.run(run_down(specs, root, HttpHealthProbe(), killer, stop_leftovers)))
    if check(settings, specs, only_problems=True):
        print("Thursday starts anyway. `uv run thursday check` shows everything.\n")
    configure_logging("launcher", logs, settings.log_level, console=False)  # the terminal gets the readable report
    console = Console(
        specs,
        dashboard_url=f"http://{LOCALHOST}:{settings.gateway_localhost_port}",
        proxy_port=settings.gateway_proxy_port,
        logs=logs,
        colour=colour_supported(sys.stdout),
    )

    def stop_leftover(spec: ServiceSpec) -> None:
        stop_for_service(logs, killer, str(spec.name), llama_folders)

    supervisor = Supervisor(
        specs,
        # An agent that crashed may have left its model server running: stop it before the agent starts again.
        SubprocessStarter(pathlib.Path.cwd(), logs, stop_leftover),
        HttpHealthProbe(),
        MonotonicClock(),
        on_change=console.change,
    )
    exit_with(asyncio.run(run_up(supervisor, root, console)))
