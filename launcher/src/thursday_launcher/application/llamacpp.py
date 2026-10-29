"""Install the built-in llama.cpp: pick the right official build for this PC, download it, check it, unpack it.

llama.cpp publishes one archive per operating system, processor and GPU backend. An NVIDIA card gets the CUDA build
and its runtime libraries (the oldest CUDA version on offer, which the most drivers support); any other GPU gets the
Vulkan build; with neither, the CPU build. Every download is checked against the SHA-256 the release publishes, and
an archive is never allowed to write outside its own folder.
"""

import json
import re
import shutil
import tarfile
import zipfile
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

_BUILD = re.compile(
    r"^llama-(?P<tag>.+?)-bin-(?P<os>win|ubuntu|macos)-(?:(?P<kind>[a-z0-9.\-]+?)-)?(?P<arch>x64|arm64)\.(?:zip|tar\.gz)$"
)
_CUDA = re.compile(r"^cuda-(\d+)\.(\d+)$")
_SYSTEMS = {"win32": "win", "linux": "ubuntu", "darwin": "macos"}
_ARCHES = {"amd64": "x64", "x86_64": "x64", "arm64": "arm64", "aarch64": "arm64"}
SERVER_NAMES = ("llama-server.exe", "llama-server")
RUNTIME_PREFIXES = ("libcudart", "libcublas", "cudart", "cublas")  # the CUDA runtime, from the `cudart-` archive
RECORD = "installed.json"


class InstallError(Exception):
    """llama.cpp could not be installed; the message says why in plain words."""


@dataclass(frozen=True, slots=True)
class Asset:
    name: str
    url: str
    size: int
    sha256: str  # empty when the release does not publish one


@dataclass(frozen=True, slots=True)
class Release:
    tag: str
    assets: tuple[Asset, ...]


@dataclass(frozen=True, slots=True)
class Choice:
    kind: str  # "cuda-12.4", "vulkan" or "cpu"
    assets: tuple[Asset, ...]  # the build, then its runtime libraries when it needs them


class ReleaseSource(Protocol):
    def latest(self) -> Release: ...

    def download(self, asset: Asset, to: Path, progress: Callable[[int], None]) -> None:
        """Write the asset to `to` and raise InstallError unless its SHA-256 matches."""
        ...


def choose(assets: Sequence[Asset], system: str, machine: str, nvidia: bool) -> Choice:
    os_name, arch = _SYSTEMS.get(system), _ARCHES.get(machine.lower())
    if os_name is None or arch is None:
        raise InstallError(f"llama.cpp publishes no build for this system ({system}, {machine}).")
    builds: dict[str, Asset] = {}
    for asset in assets:
        match = _BUILD.match(asset.name)
        if match and match["os"] == os_name and match["arch"] == arch:
            builds[match["kind"] or "cpu"] = asset
    if nvidia:
        versions = sorted(
            (int(m[1]), int(m[2]), kind) for kind in builds if (m := _CUDA.match(kind))
        )  # oldest first: the most drivers support it
        for _, _, kind in versions:
            suffix = f"-bin-{os_name}-{kind}-{arch}."
            runtime = next((a for a in assets if a.name.startswith("cudart-") and suffix in a.name), None)
            if runtime is not None:
                return Choice(kind, (builds[kind], runtime))
    if os_name == "macos" and "cpu" in builds:
        return Choice("metal", (builds["cpu"],))  # the one macOS build uses the GPU through Metal
    for kind in ("vulkan", "cpu"):
        if kind in builds:
            return Choice(kind, (builds[kind],))
    raise InstallError(f"The llama.cpp release has no build for this system ({os_name}, {arch}).")


def installed(root: Path) -> dict | None:
    """What `install` recorded, if that build's server is still on disk."""
    try:
        record = json.loads((root / RECORD).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    folder = root / str(record.get("folder", ""))
    return record if any(next(folder.rglob(name), None) for name in SERVER_NAMES) else None


def _runtime_beside_server(folder: Path) -> None:
    """Move the CUDA runtime next to `llama-server`. The CUDA backend looks for it only in its own folder, and the
    Linux archives unpack into one folder each; without this move llama.cpp finds no GPU and runs on the CPU."""
    server = next((p for name in SERVER_NAMES for p in folder.rglob(name)), None)
    if server is None:
        return
    for library in [p for p in folder.rglob("*") if p.is_file() and p.name.startswith(RUNTIME_PREFIXES)]:
        if library.parent != server.parent:
            library.replace(server.parent / library.name)


def _unpack(archive: Path, into: Path) -> None:
    into.mkdir(parents=True, exist_ok=True)
    base = into.resolve()
    if archive.name.endswith(".zip"):
        with zipfile.ZipFile(archive) as bundle:
            for member in bundle.namelist():
                if base not in (base / member).resolve().parents and (base / member).resolve() != base:
                    raise InstallError(f"{archive.name} tries to write outside its folder; it was not unpacked.")
            bundle.extractall(into)  # noqa: S202 - every member was checked to stay inside `into`
    else:
        with tarfile.open(archive) as bundle:
            try:
                bundle.extractall(into, filter="data")  # refuses paths, links and devices that leave `into`
            except tarfile.FilterError as exc:
                raise InstallError(f"{archive.name} tries to write outside its folder; it was not unpacked.") from exc


def install(
    source: ReleaseSource,
    root: Path,
    system: str,
    machine: str,
    nvidia: bool,
    say: Callable[[str], None],
    *,
    update: bool = False,
    confirm: Callable[[str], bool] | None = None,
) -> None:
    """`confirm` is asked once, with what would be downloaded and how large it is; a no installs nothing."""
    have = installed(root)
    if have is not None and not update:
        _runtime_beside_server(root / str(have["folder"]))  # repairs a build installed before this move existed
        say(f"llama.cpp {have['tag']} ({have['kind']}) is already installed")
        return
    release = source.latest()
    choice = choose(release.assets, system, machine, nvidia)
    if have is not None and (have["tag"], have["kind"]) == (release.tag, choice.kind):
        say(f"llama.cpp {release.tag} ({choice.kind}) is already the newest")
        return
    size = sum(asset.size for asset in choice.assets) / 1e6
    if confirm is not None and not confirm(f"llama.cpp {release.tag}, {choice.kind} build, about {size:.0f} MB"):
        say("llama.cpp was not downloaded; run `uv run thursday setup --with-llamacpp` when you want it")
        return
    folder = root / f"{release.tag}-{choice.kind}"
    downloads = root / "downloads"
    downloads.mkdir(parents=True, exist_ok=True)
    shutil.rmtree(folder, ignore_errors=True)
    try:
        for asset in choice.assets:
            if not asset.sha256:
                raise InstallError(f"{asset.name} has no published checksum, so it was not downloaded.")
            say(f"downloading {asset.name} ({asset.size / 1e6:.0f} MB)")
            archive = downloads / asset.name
            source.download(asset, archive, _percent(asset, say))
            _unpack(archive, folder)
        _runtime_beside_server(folder)
        if not any(next(folder.rglob(name), None) for name in SERVER_NAMES):
            raise InstallError("The downloaded build has no llama-server in it.")
    except BaseException:
        shutil.rmtree(folder, ignore_errors=True)
        raise
    finally:
        shutil.rmtree(downloads, ignore_errors=True)
    (root / RECORD).write_text(
        json.dumps({"tag": release.tag, "kind": choice.kind, "folder": folder.name}), encoding="utf-8"
    )
    for other in root.iterdir():  # one build at a time: the agents use whichever server they find
        if other.is_dir() and other != folder:
            shutil.rmtree(other, ignore_errors=True)
    say(f"installed llama.cpp {release.tag} ({choice.kind})")


def _percent(asset: Asset, say: Callable[[str], None]) -> Callable[[int], None]:
    last = -1

    def report(done: int) -> None:
        nonlocal last
        quarter = int(4 * done / asset.size) if asset.size else 4
        if quarter > last and 0 < quarter < 4:
            say(f"  {25 * quarter}%")
        last = max(last, quarter)

    return report
