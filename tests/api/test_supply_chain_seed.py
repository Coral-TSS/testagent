"""Seeded supply-chain demo: v1 has no inspection model, v2 does, requirements keep refs."""

from __future__ import annotations

import importlib.util
from pathlib import Path

from testagent.seed import seed_supply_chain

V1 = "/api/v1"


def test_seed_versions_and_requirements(db):
    first = seed_supply_chain(db)
    assert first["created"] is True
    assert seed_supply_chain(db)["created"] is False
    sut = first["sut_id"]
    with db.tx() as cur:
        cur.execute("SELECT id::text AS id, name FROM version WHERE sut_id=%s ORDER BY created_at", (sut,))
        versions = cur.fetchall()
        assert [v["name"] for v in versions] == ["v1.0", "v2.0"]
        cur.execute(
            "SELECT name FROM model_node WHERE version_id=%s AND kind='entity' AND deleted_at IS NULL",
            (versions[0]["id"],),
        )
        v1_entities = {r["name"] for r in cur.fetchall()}
        cur.execute(
            "SELECT name FROM model_node WHERE version_id=%s AND kind='entity' AND deleted_at IS NULL",
            (versions[1]["id"],),
        )
        v2_entities = {r["name"] for r in cur.fetchall()}
        assert "QualityInspection" not in v1_entities
        assert "QualityInspection" in v2_entities
        cur.execute(
            "SELECT r.code, count(l.node_id) AS nodes FROM requirement r"
            " LEFT JOIN requirement_node_link l ON l.requirement_id=r.id"
            " WHERE r.version_id=%s GROUP BY r.code ORDER BY r.code",
            (versions[0]["id"],),
        )
        v1 = cur.fetchall()
        assert [r["code"] for r in v1] == [f"REQ-{i:03d}" for i in range(1, 13)]
        assert all(r["nodes"] > 0 for r in v1)
        cur.execute("SELECT code FROM requirement WHERE version_id=%s AND code='REQ-016'", (versions[1]["id"],))
        assert cur.fetchone() is not None
        cur.execute("SELECT count(*) AS n FROM sut WHERE code='procurement'")
        assert cur.fetchone()["n"] == 0


def test_restore_script_is_repeatable(db, tmp_path):
    seed_supply_chain(db)
    path = Path(__file__).resolve().parents[2] / "ops" / "restore_supply_chain.py"
    spec = importlib.util.spec_from_file_location("restore_supply_chain", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert mod.main(["--apply", "--keep-repo"]) == 0
    assert mod.main(["--apply", "--keep-repo"]) == 0
    with db.tx() as cur:
        cur.execute("SELECT count(*) AS n FROM version v JOIN sut s ON s.id=v.sut_id WHERE s.code='supply-chain'")
        assert cur.fetchone()["n"] == 2
