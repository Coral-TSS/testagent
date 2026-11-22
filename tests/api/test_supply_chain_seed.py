"""Seeded supply-chain demo: v1 has no inspection model, v2 does, requirements keep refs."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from testagent.core.errors import AppError
from testagent.core.events import EventBus
from testagent.seed import seed_supply_chain
from testagent.services.model import ModelService
from testagent.services.requirements import RequirementService
from testagent.services.versions import VersionService

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
        cur.execute(
            "SELECT code FROM requirement WHERE version_id=%s ORDER BY code",
            (versions[1]["id"],),
        )
        assert [r["code"] for r in cur.fetchall()] == [
            "REQ-007",
            "REQ-008",
            "REQ-009",
            "REQ-013",
            "REQ-014",
            "REQ-015",
            "REQ-016",
        ]
        cur.execute(
            "SELECT code, raw_text FROM requirement WHERE version_id=%s AND code IN ('REQ-007','REQ-008','REQ-009')",
            (versions[1]["id"],),
        )
        v2_text = {r["code"]: r["raw_text"] for r in cur.fetchall()}
        assert "合格" in v2_text["REQ-007"]
        assert "超收容差" in v2_text["REQ-008"]
        assert "质检" in v2_text["REQ-009"]
        cur.execute("SELECT sealed FROM version WHERE id=%s", (versions[0]["id"],))
        assert cur.fetchone()["sealed"] is True
        cur.execute("SELECT sealed FROM version WHERE id=%s", (versions[1]["id"],))
        assert cur.fetchone()["sealed"] is False
        cur.execute(
            "SELECT method, path, request_schema, response_schema FROM api_endpoint WHERE sut_id=%s",
            (sut,),
        )
        apis = {(r["method"], r["path"]): r for r in cur.fetchall()}
        inventory = apis[("GET", "/sample/inventory")]
        assert {p["name"] for p in inventory["request_schema"]["parameters"]} == {"materialId", "warehouseId"}
        assert inventory["response_schema"]["200"]["schema"]["items"]["properties"]["onHandQty"]["type"] == "number"
        receive = apis[("POST", "/sample/orders/{order_id}/receive")]
        assert set(receive["request_schema"]["body"]["required"]) == {"lineId", "warehouseId", "receivedQty"}
        assert "receivedQty" in receive["response_schema"]["201"]["schema"]["properties"]
        decision = apis[("POST", "/sample/inspections/{inspection_id}/decision")]
        assert "passed" in decision["request_schema"]["body"]["properties"]
        assert "defectQty" in decision["response_schema"]["200"]["schema"]["properties"]
        cur.execute("SELECT count(*) AS n FROM sut WHERE code='procurement'")
        assert cur.fetchone()["n"] == 0


def test_sealed_v1_rejects_model_and_requirement_edits(db):
    seeded = seed_supply_chain(db)
    sut = seeded["sut_id"]
    with db.tx() as cur:
        cur.execute("SELECT id::text AS id, name, sealed FROM version WHERE sut_id=%s ORDER BY created_at", (sut,))
        versions = cur.fetchall()
    v1, v2 = versions[0]["id"], versions[1]["id"]
    bus = EventBus()
    model = ModelService(db, bus)
    with pytest.raises(AppError) as err:
        model.create_node(sut, {"kind": "entity", "name": "Extra", "version_id": v1})
    assert err.value.code == "CONFLICT"
    reqs = RequirementService(db, bus)
    with pytest.raises(AppError) as err:
        reqs.create(v1, {"title": "不应写入"})
    assert err.value.code == "CONFLICT"
    created = model.create_node(sut, {"kind": "entity", "name": "Extra", "version_id": v2})
    model.delete_node(created["id"], confirm=True)
    copied = VersionService(db, bus).create(sut, "v3.0", v1)
    assert copied["sealed"] is False
    with db.tx() as cur:
        cur.execute(
            "SELECT count(*) AS n FROM model_node WHERE version_id=%s AND deleted_at IS NULL",
            (copied["id"],),
        )
        assert cur.fetchone()["n"] > 0


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
