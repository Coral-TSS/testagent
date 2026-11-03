"""Versions: lifecycle, freeze (with model snapshot) and unfreeze (reason required)."""

from __future__ import annotations

from testagent.core.actor import current_actor
from testagent.core.errors import AppError
from testagent.core.events import EventBus
from testagent.services.changelog import log_change
from testagent.services.guards import ensure_human
from testagent.services.model import ModelService
from testagent.services.state import transition


class VersionService:
    def __init__(self, db, bus: EventBus, actor: str | None = None):
        self.db = db
        self.bus = bus
        self.actor = actor or current_actor()

    @staticmethod
    def _get(cur, version_id, lock: bool = False) -> dict:
        cur.execute("SELECT * FROM version WHERE id=%s" + (" FOR UPDATE" if lock else ""), (version_id,))
        row = cur.fetchone()
        if row is None:
            raise AppError("NOT_FOUND", "Version not found")
        return row

    def create(self, sut_id, name: str) -> dict:
        with self.db.tx() as cur:
            cur.execute("SELECT 1 FROM sut WHERE id=%s", (sut_id,))
            if cur.fetchone() is None:
                raise AppError("NOT_FOUND", "SUT not found")
            cur.execute("INSERT INTO version(sut_id, name) VALUES (%s,%s) RETURNING *", (sut_id, name))
            row = cur.fetchone()
            log_change(cur, "version", row["id"], "create", self.actor, {"name": name})
        self.bus.publish("version.created", {"id": str(row["id"])})
        return row

    def list(self, sut_id) -> list[dict]:
        with self.db.tx() as cur:
            cur.execute(
                "SELECT v.*, (SELECT count(*) FROM requirement r WHERE r.version_id=v.id)"
                " AS requirement_count FROM version v WHERE sut_id=%s ORDER BY created_at",
                (sut_id,),
            )
            return cur.fetchall()

    def get(self, version_id) -> dict:
        with self.db.tx() as cur:
            row = self._get(cur, version_id)
            cur.execute("SELECT code, name FROM sut WHERE id=%s", (row["sut_id"],))
            sut = cur.fetchone()
            return {**row, "sut_code": sut["code"], "sut_name": sut["name"]}

    def rename(self, version_id, name: str) -> dict:
        with self.db.tx() as cur:
            self._get(cur, version_id, lock=True)
            cur.execute("UPDATE version SET name=%s WHERE id=%s RETURNING *", (name, version_id))
            row = cur.fetchone()
            log_change(cur, "version", version_id, "update", self.actor, {"name": name})
        return row

    def history(self, version_id) -> list[dict]:
        with self.db.tx() as cur:
            self._get(cur, version_id)
            cur.execute(
                "SELECT action, actor, diff, created_at FROM change_log"
                " WHERE entity='version' AND entity_id=%s ORDER BY id",
                (str(version_id),),
            )
            return cur.fetchall()

    def freeze(self, version_id) -> dict:
        """All requirements confirmed → snapshot the SUT model and lock requirements (BR-02)."""
        ensure_human(self.actor, "Freeze version")
        model = ModelService(self.db, self.bus, self.actor)
        with self.db.tx() as cur:
            version = self._get(cur, version_id, lock=True)
            transition("version", version["status"], "requirements_frozen")
            cur.execute(
                "SELECT code, status FROM requirement WHERE version_id=%s ORDER BY code",
                (version_id,),
            )
            reqs = cur.fetchall()
            if not reqs:
                raise AppError("VALIDATION", "The version has no requirements and cannot be frozen")
            pending = [r["code"] for r in reqs if r["status"] != "confirmed"]
            if pending:
                raise AppError(
                    "VALIDATION",
                    f"There are still {len(pending)} unconfirmed requirement(s); cannot freeze",
                    related=pending,
                )
            snapshot = model.create_snapshot(version["sut_id"], version_id, cur=cur)
            cur.execute(
                "UPDATE version SET status='requirements_frozen', frozen_at=now(),"
                " model_snapshot_id=%s WHERE id=%s RETURNING *",
                (snapshot["id"], version_id),
            )
            row = cur.fetchone()
            log_change(
                cur,
                "version",
                version_id,
                "freeze",
                self.actor,
                {"snapshot_id": snapshot["id"], "digest": snapshot["digest"]},
            )
        self.bus.publish("version.frozen", {"id": str(version_id), "snapshot_id": str(snapshot["id"])})
        return row

    def unfreeze(self, version_id, reason: str | None) -> dict:
        ensure_human(self.actor, "Unfreeze version")
        with self.db.tx() as cur:
            version = self._get(cur, version_id, lock=True)
            transition("version", version["status"], "planning", reason=reason)
            cur.execute(
                "UPDATE version SET status='planning', frozen_at=NULL, model_snapshot_id=NULL WHERE id=%s RETURNING *",
                (version_id,),
            )
            row = cur.fetchone()
            log_change(
                cur,
                "version",
                version_id,
                "unfreeze",
                self.actor,
                {"reason": reason.strip(), "previous_snapshot_id": version["model_snapshot_id"]},
            )
        self.bus.publish("version.unfrozen", {"id": str(version_id)})
        return row

    def set_status(self, version_id, target: str) -> dict:
        """planning→frozen and back use freeze/unfreeze; this covers testing and closed."""
        if target in ("requirements_frozen", "planning"):
            raise AppError("VALIDATION", "Use the freeze/unfreeze endpoints")
        ensure_human(self.actor, "Change version status")
        with self.db.tx() as cur:
            version = self._get(cur, version_id, lock=True)
            transition("version", version["status"], target)
            cur.execute("UPDATE version SET status=%s WHERE id=%s RETURNING *", (target, version_id))
            row = cur.fetchone()
            log_change(cur, "version", version_id, "status", self.actor, {"status": target})
        self.bus.publish(f"version.{target}", {"id": str(version_id)})
        return row
