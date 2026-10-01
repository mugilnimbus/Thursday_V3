import pytest
from thursday_tool_server.application.files import FileTools, ToolFailure
from thursday_tool_server.domain.workspace import SandboxViolation, Workspace


def tools(layout, limit: int = 30000) -> FileTools:
    return FileTools(Workspace(layout["ws"]), limit)


def test_write_read_edit_round_trip(layout) -> None:
    t = tools(layout)
    assert "created" in t.write("src/app.py", "x = 1\ny = 2\n")
    assert t.read("src/app.py") == "     1\tx = 1\n     2\ty = 2"
    t.edit("src/app.py", "y = 2", "y = 3")
    assert "y = 3" in t.read("src/app.py")


def test_edit_requires_a_unique_match(layout) -> None:
    t = tools(layout)
    t.write("a.txt", "x\nx\n")
    with pytest.raises(ToolFailure, match="found 2 times"):
        t.edit("a.txt", "x", "y")
    assert "2 replacement" in t.edit("a.txt", "x", "y", replace_all=True)


def test_crlf_is_preserved_by_edit(layout) -> None:
    (layout["ws"] / "w.txt").write_bytes(b"a\r\nb\r\n")
    tools(layout).edit("w.txt", "b", "c")
    assert (layout["ws"] / "w.txt").read_bytes() == b"a\r\nc\r\n"


def test_binary_file_is_not_dumped(layout) -> None:
    (layout["ws"] / "b.bin").write_bytes(b"\x00\x01\x02")
    with pytest.raises(ToolFailure, match="binary"):
        tools(layout).read("b.bin")


def test_output_is_capped(layout) -> None:
    t = tools(layout, limit=1000)
    t.write("big.txt", "line\n" * 5000)
    assert t.read("big.txt").endswith("[output truncated at 1000 characters]")


def test_writes_outside_are_refused_before_any_io(layout) -> None:
    with pytest.raises(SandboxViolation):
        tools(layout).write("../outside/pwned.txt", "x")
    assert not (layout["outside"] / "pwned.txt").exists()


def test_delete_refuses_root_and_non_empty_without_recursive(layout) -> None:
    t = tools(layout)
    with pytest.raises(SandboxViolation):
        t.delete(".")
    t.write("d/x.txt", "x")
    with pytest.raises(ToolFailure, match="not empty"):
        t.delete("d")
    assert "deleted folder" in t.delete("d", recursive=True)


def test_deleting_a_junction_removes_only_the_link(layout, junction) -> None:
    junction(layout["ws"] / "escape", layout["outside"])
    assert "removed link" in tools(layout).delete("escape")
    assert (layout["outside"] / "secret.txt").read_text(encoding="utf-8") == "secret"


def test_recursive_delete_does_not_follow_an_inner_junction(layout, junction) -> None:
    (layout["ws"] / "d").mkdir()
    junction(layout["ws"] / "d" / "escape", layout["outside"])
    tools(layout).delete("d", recursive=True)
    assert (layout["outside"] / "secret.txt").exists()
    assert not (layout["ws"] / "d").exists()


def test_patch_creates_and_updates(layout) -> None:
    t = tools(layout)
    t.patch("new.txt", "@@ -0,0 +1,1 @@\n+hi\n")
    assert (layout["ws"] / "new.txt").read_text(encoding="utf-8") == "hi\n"
    with pytest.raises(ToolFailure, match="does not match"):
        t.patch("new.txt", "@@ -1,1 +1,1 @@\n-nope\n+x\n")
