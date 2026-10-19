"""Where the built-in llama.cpp and the model files are on disk. Nothing here starts a program."""

import sys
from pathlib import Path

from thursday_llm.providers.base import NO_MODEL, ModelInfo, ProviderError


def server_exe(folder: str) -> Path:
    """The newest `llama-server` under the install folder (`thursday setup` puts each build in its own folder)."""
    name = "llama-server.exe" if sys.platform == "win32" else "llama-server"
    if folder and Path(folder).is_dir():
        found = sorted(Path(folder).rglob(name), key=lambda path: path.stat().st_mtime)
        if found:
            return found[-1]
    raise ProviderError("llama.cpp is not installed. Run `uv run thursday setup` in the Thursday folder.")


def models_dir(folder: str) -> Path:
    if not folder or not Path(folder).is_dir():
        raise ProviderError("Choose the folder that holds your model files (.gguf) in Settings.")
    return Path(folder)


def projector_beside(model: Path) -> Path | None:
    found = sorted(model.parent.glob("mmproj*.gguf"))
    return found[0] if found else None


def projector_megabytes(model: Path) -> int:
    """How much memory the projector beside a model takes on a card (its file size). 0 without one."""
    projector = projector_beside(model)
    return round(projector.stat().st_size / 2**20) if projector is not None else 0


def scan(folder: str, loaded_key: str | None) -> list[ModelInfo]:
    """Every model file under the models folder, named by its path inside the folder. Projector files are not models."""
    root = models_dir(folder)
    models = []
    for path in sorted(root.rglob("*.gguf")):
        if path.name.lower().startswith("mmproj"):
            continue
        projector = projector_beside(path)
        key = path.relative_to(root).as_posix()
        models.append(
            ModelInfo(key, key == loaded_key, None, None, path.stat().st_size, projector.name if projector else None)
        )
    return models


def resolve(folder: str, key: str) -> Path:
    """The model file a key names. Never a path outside the models folder."""
    if not key:
        raise ProviderError(NO_MODEL)
    root = models_dir(folder).resolve()
    path = (root / key).resolve()
    if root not in path.parents or not path.is_file():
        raise ProviderError(f"The model file is not in the models folder: {key}. Choose one from the list in Settings.")
    return path
