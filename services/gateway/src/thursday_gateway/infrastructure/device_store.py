"""The paired devices table. A device's token is never stored, only its SHA-256 hash."""

from typing import Any

from thursday_gateway.infrastructure.store import Store


class DeviceStore:
    def __init__(self, store: Store) -> None:
        self._store = store
        with store.tx() as db:
            db.execute(
                "create table if not exists devices (device_id text primary key, name text not null, "
                "token_hash text not null unique, created_at text not null, revoked integer not null default 0)"
            )
            columns = {r[1] for r in db.execute("pragma table_info(devices)")}
            if "last_seen" not in columns:
                db.execute("alter table devices add column last_seen text")

    def add(self, device_id: str, name: str, token_hash: str, stamp: str) -> None:
        with self._store.tx() as db:
            db.execute(
                "insert into devices (device_id, name, token_hash, created_at, revoked, last_seen) "
                "values (?,?,?,?,0,?)",
                (device_id, name, token_hash, stamp, stamp),
            )

    def token_hashes(self) -> list[dict[str, Any]]:
        """`device_id` and `token_hash` of every device that is not revoked."""
        rows = self._store.query("select device_id, token_hash from devices where revoked = 0")
        return [dict(r) for r in rows]

    def seen(self, device_id: str, stamp: str) -> None:
        with self._store.tx() as db:
            db.execute("update devices set last_seen = ? where device_id = ?", (stamp, device_id))

    def list(self) -> list[dict[str, Any]]:
        rows = self._store.query(
            "select device_id, name, created_at, last_seen from devices where revoked = 0 order by created_at"
        )
        return [dict(r) for r in rows]

    def revoke(self, device_id: str) -> bool:
        """False when there is no such device, or it was revoked already."""
        with self._store.tx() as db:
            changed = db.execute(
                "update devices set revoked = 1 where device_id = ? and revoked = 0", (device_id,)
            ).rowcount
        return bool(changed)
