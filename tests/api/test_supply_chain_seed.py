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
            "SELECT r.code, r.title, r.priority, r.raw_text, r.structured, r.status,"
            " (SELECT count(*) FROM requirement_node_link l WHERE l.requirement_id=r.id) AS nodes,"
            " (SELECT count(*) FROM requirement_attribute_link l WHERE l.requirement_id=r.id) AS attrs,"
            " (SELECT count(*) FROM requirement_link_ref l WHERE l.requirement_id=r.id) AS links,"
            " (SELECT count(*) FROM requirement_person p WHERE p.requirement_id=r.id) AS people"
            " FROM requirement r WHERE r.version_id=%s ORDER BY r.code",
            (versions[1]["id"],),
        )
        v2_rows = cur.fetchall()
        assert [(r["code"], r["title"]) for r in v2_rows] == [
            ("REQ-007", "下达采购订单给供应商"),
            ("REQ-008", "按订单收货"),
            ("REQ-009", "收货过账入库"),
            ("REQ-013", "物料质检要求"),
            ("REQ-014", "创建质检单"),
            ("REQ-015", "判定质检"),
            ("REQ-016", "供应商准入"),
        ]
        by_code = {r["code"]: r for r in v2_rows}
        assert "合格" in by_code["REQ-007"]["raw_text"] and "冻结" not in by_code["REQ-007"]["raw_text"]
        assert "超收容差" in by_code["REQ-008"]["raw_text"]
        assert "质检合格" in by_code["REQ-009"]["raw_text"]
        assert "才能按 REQ-009 决定是否入库" in by_code["REQ-013"]["raw_text"]
        assert by_code["REQ-014"]["raw_text"] == "未过账的收货单，若物料需要质检，可创建质检单，初始结论为待判定。"
        assert "不合格则该收货单不得过账入库" in by_code["REQ-015"]["raw_text"]
        assert (
            by_code["REQ-016"]["raw_text"]
            == "仅状态为合格的供应商可被下达采购订单。潜在供应商不能下达；冻结规则同时适用。"
        )
        for row in v2_rows:
            assert row["priority"] == "P1"
            assert row["raw_text"]
            assert row["status"] == "draft"
            assert not row["structured"]
            assert row["nodes"] == row["attrs"] == row["links"] == row["people"] == 0
        cur.execute(
            "SELECT raw_text FROM requirement WHERE version_id=%s AND code='REQ-007'",
            (versions[0]["id"],),
        )
        assert "冻结" in cur.fetchone()["raw_text"]
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
