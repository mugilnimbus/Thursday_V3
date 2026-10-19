import sqlite3
from pathlib import Path

from thursday_runtime.call_meta import CHAT_ID_META_KEY, chat_id_from
from thursday_runtime.sqlite_care import compact_all, compact_if_worthwhile


def filled(path: Path, rows: int) -> None:
    db = sqlite3.connect(path, isolation_level=None)
    db.execute("pragma journal_mode=wal")
    db.execute("create table if not exists notes (id integer primary key, body text not null)")
    db.executemany("insert into notes (body) values (?)", [("x" * 2000,) for _ in range(rows)])
    db.close()


def test_a_file_with_much_unused_space_is_compacted_and_keeps_its_rows(tmp_path: Path) -> None:
    path = tmp_path / "data.sqlite"
    filled(path, 2000)
    db = sqlite3.connect(path, isolation_level=None)
    db.execute("delete from notes where id > 100")
    db.close()
    before = path.stat().st_size
    given_back = compact_if_worthwhile(path, min_free_bytes=64 * 1024)
    assert given_back > 0 and path.stat().st_size < before / 2
    assert sqlite3.connect(path).execute("select count(*) from notes").fetchone()[0] == 100


def test_a_file_with_little_unused_space_or_no_file_is_left_alone(tmp_path: Path) -> None:
    path = tmp_path / "data.sqlite"
    filled(path, 200)
    size = path.stat().st_size
    assert compact_if_worthwhile(path) == 0 and path.stat().st_size == size
    assert compact_if_worthwhile(tmp_path / "missing.sqlite") == 0
    (tmp_path / "broken.sqlite").write_bytes(b"this is not a database")
    assert compact_all([tmp_path / "broken.sqlite", tmp_path / "missing.sqlite"]) == 0, "never stops a start"


def test_the_chat_of_a_tool_call_is_read_only_when_well_formed() -> None:
    assert chat_id_from({CHAT_ID_META_KEY: "chat-7fd004a911ca"}) == "chat-7fd004a911ca"
    assert chat_id_from({CHAT_ID_META_KEY: "../../etc"}) is None
    assert chat_id_from({CHAT_ID_META_KEY: 7}) is None
    assert chat_id_from({}) is None and chat_id_from(None) is None
