"""Installing the built-in llama.cpp, against a stand-in release (small archives made in the test)."""

import hashlib
import io
import tarfile
import zipfile
from collections.abc import Callable
from pathlib import Path

import pytest
from thursday_launcher.application.llamacpp import Asset, InstallError, Release, choose, install, installed

NAMES = [
    "cudart-llama-bin-win-cuda-12.4-x64.zip",
    "cudart-llama-bin-win-cuda-13.4-x64.zip",
    "cudart-llama-b9-bin-ubuntu-cuda-12.8-x64.tar.gz",
    "llama-b9-bin-macos-arm64.tar.gz",
    "llama-b9-bin-ubuntu-cuda-12.8-x64.tar.gz",
    "llama-b9-bin-ubuntu-openvino-2026.4.1-x64.tar.gz",
    "llama-b9-bin-ubuntu-vulkan-x64.tar.gz",
    "llama-b9-bin-ubuntu-x64.tar.gz",
    "llama-b9-bin-win-cpu-arm64.zip",
    "llama-b9-bin-win-cpu-x64.zip",
    "llama-b9-bin-win-cuda-12.4-x64.zip",
    "llama-b9-bin-win-cuda-13.4-x64.zip",
    "llama-b9-bin-win-vulkan-x64.zip",
    "llama-b9-ui.tar.gz",
]
ASSETS = [Asset(name, f"https://example.invalid/{name}", 1, "0" * 64) for name in NAMES]


def names(system: str, machine: str, nvidia: bool) -> tuple[str, list[str]]:
    choice = choose(ASSETS, system, machine, nvidia)
    return choice.kind, [a.name for a in choice.assets]


def test_an_nvidia_pc_gets_the_oldest_cuda_build_with_its_runtime() -> None:
    assert names("win32", "AMD64", True) == (
        "cuda-12.4",
        ["llama-b9-bin-win-cuda-12.4-x64.zip", "cudart-llama-bin-win-cuda-12.4-x64.zip"],
    )
    assert names("linux", "x86_64", True)[1] == [
        "llama-b9-bin-ubuntu-cuda-12.8-x64.tar.gz",
        "cudart-llama-b9-bin-ubuntu-cuda-12.8-x64.tar.gz",
    ]


def test_other_pcs_get_vulkan_then_cpu_and_a_mac_its_one_build() -> None:
    assert names("win32", "AMD64", False) == ("vulkan", ["llama-b9-bin-win-vulkan-x64.zip"])
    assert names("win32", "ARM64", True) == ("cpu", ["llama-b9-bin-win-cpu-arm64.zip"]), "no CUDA build for arm64"
    assert names("linux", "x86_64", False) == ("vulkan", ["llama-b9-bin-ubuntu-vulkan-x64.tar.gz"])
    assert names("darwin", "arm64", False) == ("metal", ["llama-b9-bin-macos-arm64.tar.gz"])


def test_a_system_without_a_build_is_refused_plainly() -> None:
    with pytest.raises(InstallError, match="no build for this system"):
        choose(ASSETS, "darwin", "x86_64", False)
    with pytest.raises(InstallError, match="no build for this system"):
        choose(ASSETS, "freebsd", "amd64", False)


def zipped(files: dict[str, bytes]) -> bytes:
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as bundle:
        for name, data in files.items():
            bundle.writestr(name, data)
    return out.getvalue()


class FakeReleases:
    """Serves archives from memory and checks the checksum the way the real source does."""

    def __init__(self, tag: str, files: dict[str, bytes], *, wrong_checksum: str | None = None) -> None:
        self.files = files
        self.downloaded: list[str] = []
        self.release = Release(
            tag,
            tuple(
                Asset(
                    name,
                    f"https://example.invalid/{name}",
                    len(data),
                    "f" * 64 if name == wrong_checksum else hashlib.sha256(data).hexdigest(),
                )
                for name, data in files.items()
            ),
        )

    def latest(self) -> Release:
        return self.release

    def download(self, asset: Asset, to: Path, progress: Callable[[int], None]) -> None:
        self.downloaded.append(asset.name)
        data = self.files[asset.name]
        to.write_bytes(data)
        progress(len(data))
        if hashlib.sha256(data).hexdigest() != asset.sha256:
            to.unlink()
            raise InstallError(f"{asset.name} does not match its published checksum; it was deleted.")


def windows_release(tag: str = "b9", **options: str | None) -> FakeReleases:
    return FakeReleases(
        tag,
        {
            f"llama-{tag}-bin-win-cuda-12.4-x64.zip": zipped({"llama-server.exe": b"server", "llama.dll": b"lib"}),
            "cudart-llama-bin-win-cuda-12.4-x64.zip": zipped({"cudart64_12.dll": b"runtime"}),
        },
        **options,  # type: ignore[arg-type]
    )


def test_install_downloads_checks_and_unpacks_the_build_and_its_runtime_together(tmp_path: Path) -> None:
    said: list[str] = []
    source = windows_release()
    install(source, tmp_path, "win32", "AMD64", True, said.append)
    folder = tmp_path / "b9-cuda-12.4"
    assert (folder / "llama-server.exe").read_bytes() == b"server" and (folder / "cudart64_12.dll").exists()
    assert installed(tmp_path) == {"tag": "b9", "kind": "cuda-12.4", "folder": "b9-cuda-12.4"}
    assert not (tmp_path / "downloads").exists(), "the archives are removed after unpacking"
    assert said[-1] == "installed llama.cpp b9 (cuda-12.4)"

    install(source, tmp_path, "win32", "AMD64", True, said.append)
    assert len(source.downloaded) == 2 and "already installed" in said[-1], "a second setup downloads nothing"


def tarred(files: dict[str, bytes]) -> bytes:
    out = io.BytesIO()
    with tarfile.open(fileobj=out, mode="w:gz") as bundle:
        for name, data in files.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            bundle.addfile(info, io.BytesIO(data))
    return out.getvalue()


def test_on_linux_the_cuda_runtime_is_moved_next_to_the_server_so_the_gpu_is_found(tmp_path: Path) -> None:
    # The real Linux archives unpack into one folder each, and libggml-cuda.so looks only in its own folder.
    source = FakeReleases(
        "b9",
        {
            "llama-b9-bin-ubuntu-cuda-12.8-x64.tar.gz": tarred(
                {"llama-b9/llama-server": b"server", "llama-b9/libggml-cuda.so": b"cuda"}
            ),
            "cudart-llama-b9-bin-ubuntu-cuda-12.8-x64.tar.gz": tarred(
                {"cudart-llama-b9/libcudart.so.12": b"rt", "cudart-llama-b9/libcublas.so.12": b"blas"}
            ),
        },
    )
    install(source, tmp_path, "linux", "x86_64", True, lambda _: None)
    server_dir = tmp_path / "b9-cuda-12.8" / "llama-b9"
    assert (server_dir / "libcudart.so.12").read_bytes() == b"rt" and (server_dir / "libcublas.so.12").exists()

    (server_dir / "libcudart.so.12").replace(tmp_path / "b9-cuda-12.8" / "cudart-llama-b9" / "libcudart.so.12")
    install(source, tmp_path, "linux", "x86_64", True, lambda _: None)
    assert (server_dir / "libcudart.so.12").exists(), "setup again repairs a build installed the old way"


def test_update_replaces_the_old_build_only_when_there_is_a_newer_one(tmp_path: Path) -> None:
    said: list[str] = []
    install(windows_release("b9"), tmp_path, "win32", "AMD64", True, said.append)
    same = windows_release("b9")
    install(same, tmp_path, "win32", "AMD64", True, said.append, update=True)
    assert same.downloaded == [] and "already the newest" in said[-1]
    install(windows_release("b10"), tmp_path, "win32", "AMD64", True, said.append, update=True)
    assert [p.name for p in tmp_path.iterdir() if p.is_dir()] == ["b10-cuda-12.4"]
    assert (installed(tmp_path) or {})["tag"] == "b10"


def test_a_download_that_fails_its_checksum_installs_nothing(tmp_path: Path) -> None:
    source = windows_release(wrong_checksum="cudart-llama-bin-win-cuda-12.4-x64.zip")
    with pytest.raises(InstallError, match="does not match its published checksum"):
        install(source, tmp_path, "win32", "AMD64", True, lambda _: None)
    assert installed(tmp_path) is None and not (tmp_path / "b9-cuda-12.4").exists()


def test_a_build_without_a_published_checksum_is_not_downloaded(tmp_path: Path) -> None:
    source = windows_release()
    source.release = Release("b9", tuple(Asset(a.name, a.url, a.size, "") for a in source.release.assets))
    with pytest.raises(InstallError, match="no published checksum"):
        install(source, tmp_path, "win32", "AMD64", True, lambda _: None)
    assert source.downloaded == []


def test_an_archive_that_writes_outside_its_folder_is_refused(tmp_path: Path) -> None:
    root = tmp_path / "llamacpp"
    bad_zip = FakeReleases("b9", {"llama-b9-bin-win-vulkan-x64.zip": zipped({"../../evil.exe": b"x"})})
    with pytest.raises(InstallError, match="outside its folder"):
        install(bad_zip, root, "win32", "AMD64", False, lambda _: None)

    packed = io.BytesIO()
    with tarfile.open(fileobj=packed, mode="w:gz") as bundle:
        info = tarfile.TarInfo("../../evil")
        info.size = 1
        bundle.addfile(info, io.BytesIO(b"x"))
    bad_tar = FakeReleases("b9", {"llama-b9-bin-ubuntu-x64.tar.gz": packed.getvalue()})
    with pytest.raises(InstallError, match="outside its folder"):
        install(bad_tar, root, "linux", "x86_64", False, lambda _: None)
    assert not (tmp_path / "evil.exe").exists() and not (tmp_path / "evil").exists() and installed(root) is None


def test_setup_asks_before_downloading_and_a_no_installs_nothing(tmp_path: Path) -> None:
    said: list[str] = []
    asked: list[str] = []
    source = windows_release()

    def no(what: str) -> bool:
        asked.append(what)
        return False

    install(source, tmp_path, "win32", "AMD64", True, said.append, confirm=no)
    assert asked == ["llama.cpp b9, cuda-12.4 build, about 0 MB"] and source.downloaded == []
    assert installed(tmp_path) is None and "--with-llamacpp" in said[-1]

    install(source, tmp_path, "win32", "AMD64", True, said.append, confirm=lambda _: True)
    assert installed(tmp_path) is not None
    install(source, tmp_path, "win32", "AMD64", True, said.append, confirm=no)
    assert len(asked) == 1, "nothing is asked when it is already installed"
