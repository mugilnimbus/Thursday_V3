"""The layer rule, checked on every run: inside a service, dependencies point inward.

    domain  <-  application  <-  transport, infrastructure        (bootstrap may import all of them)

`application` says what it needs as interfaces in its `ports` module, `infrastructure` holds the classes that fit
them, and only `bootstrap` connects the two. So a module in `application` or `transport` that imports a storage
or client class from `infrastructure` fails this test, with the file, the line and the import named.
"""

import ast
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
LAYERS = ("domain", "application", "transport", "infrastructure", "bootstrap")
MAY_IMPORT = {
    "domain": {"domain"},
    "application": {"domain", "application"},
    "transport": {"domain", "application", "transport"},
    "infrastructure": {"domain", "application", "infrastructure"},
    "bootstrap": set(LAYERS),
}


def layered_packages(root: Path = ROOT) -> list[Path]:
    """Every package that is split into layers: the services and the launcher."""
    candidates = [*(root / "services").glob("*/src/*"), *(root / "launcher" / "src").glob("*")]
    return sorted(p for p in candidates if (p / "application").is_dir())


def violations(package: Path) -> list[str]:
    found = []
    for path in sorted(package.rglob("*.py")):
        layer = path.relative_to(package).parts[0]
        if layer not in MAY_IMPORT:
            continue  # the package's own __init__ and __main__
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                modules = [node.module]
            elif isinstance(node, ast.Import):
                modules = [alias.name for alias in node.names]
            else:
                continue
            for module in modules:
                parts = module.split(".")
                own_layer = parts[0] == package.name and len(parts) > 1 and parts[1] in LAYERS
                if own_layer and parts[1] not in MAY_IMPORT[layer]:
                    found.append(f"{path.relative_to(package).as_posix()}:{node.lineno} imports {module}")
    return found


@pytest.mark.parametrize("package", layered_packages(), ids=lambda p: p.name)
def test_dependencies_point_inward(package: Path) -> None:
    broken = violations(package)
    assert not broken, (
        f"{package.name}: these imports cross the layers the wrong way. Name what is needed as a port in "
        "application/ports.py and let bootstrap pass the implementation in.\n  " + "\n  ".join(broken)
    )


def test_every_service_is_checked() -> None:
    names = {p.name for p in layered_packages()}
    assert {"thursday_gateway", "thursday_main_agent", "thursday_voice_agent", "thursday_launcher"} <= names


def test_a_wrong_import_is_reported(tmp_path: Path) -> None:
    package = tmp_path / "services" / "demo" / "src" / "thursday_demo"
    for layer in ("application", "infrastructure"):
        (package / layer).mkdir(parents=True)
    (package / "infrastructure" / "store.py").write_text("class Store: ...\n", encoding="utf-8")
    (package / "application" / "logic.py").write_text(
        "from thursday_demo.infrastructure.store import Store\n", encoding="utf-8"
    )
    assert layered_packages(tmp_path) == [package]
    assert violations(package) == ["application/logic.py:1 imports thursday_demo.infrastructure.store"]
