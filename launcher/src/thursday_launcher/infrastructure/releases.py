"""The official llama.cpp releases on GitHub, and whether this PC has an NVIDIA card."""

import hashlib
import shutil
import subprocess
from collections.abc import Callable
from pathlib import Path

import httpx

from thursday_launcher.application.llamacpp import Asset, InstallError, Release

REPOSITORY = "https://api.github.com/repos/ggml-org/llama.cpp"
DOWNLOAD_HOSTS = ("https://github.com/ggml-org/llama.cpp/releases/download/",)
BUILD_POINTER = "nightly-tag.txt"  # a stable release names the build that carries its binaries


class GitHubReleases:
    def __init__(self, client: httpx.Client | None = None) -> None:
        self._client = client or httpx.Client(
            timeout=60, follow_redirects=True, headers={"Accept": "application/vnd.github+json"}
        )

    def _release(self, path: str) -> Release:
        try:
            response = self._client.get(f"{REPOSITORY}/releases/{path}")
            response.raise_for_status()
            data = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise InstallError(f"Could not reach the llama.cpp releases on GitHub ({type(exc).__name__}).") from exc
        assets = tuple(
            Asset(
                a["name"],
                a["browser_download_url"],
                int(a.get("size") or 0),
                str(a.get("digest") or "").removeprefix("sha256:"),
            )
            for a in data.get("assets", [])
        )
        return Release(str(data.get("tag_name", "")), assets)

    def latest(self) -> Release:
        release = self._release("latest")
        pointer = next((a for a in release.assets if a.name == BUILD_POINTER), None)
        if pointer is None:
            return release
        try:
            response = self._client.get(pointer.url)
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise InstallError(f"Could not read which llama.cpp build to use ({type(exc).__name__}).") from exc
        if pointer.sha256 and hashlib.sha256(response.content).hexdigest() != pointer.sha256:
            raise InstallError("The llama.cpp build pointer does not match its published checksum.")
        tag = response.text.strip()
        if not tag or not tag.replace(".", "").replace("-", "").replace("_", "").isalnum():
            raise InstallError("The llama.cpp release names an unusable build.")
        return self._release(f"tags/{tag}")

    def download(self, asset: Asset, to: Path, progress: Callable[[int], None]) -> None:
        if not asset.url.startswith(DOWNLOAD_HOSTS):
            raise InstallError(f"{asset.name} is not hosted by the llama.cpp project; it was not downloaded.")
        digest = hashlib.sha256()
        done = 0
        try:
            with self._client.stream("GET", asset.url) as response, to.open("wb") as out:
                response.raise_for_status()
                for chunk in response.iter_bytes(1 << 20):
                    out.write(chunk)
                    digest.update(chunk)
                    done += len(chunk)
                    progress(done)
        except httpx.HTTPError as exc:
            to.unlink(missing_ok=True)
            raise InstallError(f"Downloading {asset.name} failed ({type(exc).__name__}).") from exc
        if digest.hexdigest() != asset.sha256.lower():
            to.unlink(missing_ok=True)
            raise InstallError(f"{asset.name} does not match its published checksum; it was deleted.")

    def close(self) -> None:
        self._client.close()


def has_nvidia() -> bool:
    """True when the NVIDIA driver's own tool is installed and reports a card."""
    tool = shutil.which("nvidia-smi")
    if tool is None:
        return False
    try:
        result = subprocess.run(  # noqa: S603 - the driver's own tool, found on PATH, with fixed arguments
            [tool, "--query-gpu=name", "--format=csv,noheader"], capture_output=True, text=True, timeout=20, check=False
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return result.returncode == 0 and bool(result.stdout.strip())
