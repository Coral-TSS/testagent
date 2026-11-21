"""Human-readable labels for UUIDs shown in the UI and logs: "name (code)",
plus the object kind and the page that shows it."""

from __future__ import annotations

import json
import re

UUID_RE = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")

PURPOSE_LABEL = {
    "structure_requirement": "需求结构化",
    "complete_model": "模型补全",
    "generate_strategy": "策略生成",
    "generate_cases": "用例生成",
    "complete_case": "用例 AI 补全",
    "automate_case": "用例自动化",
    "execute_case_browser": "浏览器执行",
    "execute_case_api": "API 执行",
    "analyze_failure": "失败分析",
    "summarize_report": "报告摘要",
    "digest_correction": "纠正处理",
}

# (kind, SQL returning id, label, path) — tried in order until every id is resolved
QUERIES = (
    (
        "SUT",
        "SELECT id::text AS id, name || ' (' || code || ')' AS label,"
        " '/suts/' || id AS path FROM sut WHERE id = ANY(%(ids)s)",
    ),
    (
        "Version",
        "SELECT id::text AS id, '版本 ' || name AS label, '/versions/' || id AS path"
        " FROM version WHERE id = ANY(%(ids)s)",
    ),
    (
        "Requirement",
        "SELECT id::text AS id, title || ' (' || code || ')' AS label,"
        " '/versions/' || version_id || '?req=' || id AS path FROM requirement"
        " WHERE id = ANY(%(ids)s)",
    ),
    (
        "Case",
        "SELECT id::text AS id, title || ' (' || code || ')' AS label, '/cases/' || id AS path"
        " FROM test_case WHERE id = ANY(%(ids)s)",
    ),
    (
        "Task",
        "SELECT id::text AS id, name AS label, '/tasks/' || id AS path FROM test_task WHERE id = ANY(%(ids)s)",
    ),
    (
        "Run",
        "SELECT r.id::text AS id, t.name || ' · ' || to_char(r.created_at AT TIME ZONE"
        " 'UTC', 'MM-DD HH24:MI') AS label, '/runs/' || r.id AS path FROM task_run r"
        " JOIN test_task t ON t.id=r.task_id WHERE r.id = ANY(%(ids)s)",
    ),
    (
        "Execution",
        "SELECT e.id::text AS id, c.title || ' (' || c.code || ') · ' || e.status AS label,"
        " '/executions/' || e.id AS path FROM case_execution e JOIN test_case c"
        " ON c.id=e.case_id WHERE e.id = ANY(%(ids)s)",
    ),
    (
        "Defect",
        "SELECT id::text AS id, title || coalesce(' (' || code || ')', '') AS label,"
        " '/defects/' || id AS path FROM defect WHERE id = ANY(%(ids)s)",
    ),
    (
        "Report",
        "SELECT id::text AS id, CASE scope_type WHEN 'task_run' THEN '任务报告'"
        " ELSE '版本报告' END AS label, '/reports/' || id AS path FROM report"
        " WHERE id = ANY(%(ids)s)",
    ),
    (
        "Agent run",
        "SELECT id::text AS id, purpose AS label, '/agent/runs?run=' || id AS path"
        " FROM agent_run WHERE id = ANY(%(ids)s)",
    ),
    (
        "Model node",
        "SELECT id::text AS id, name || CASE WHEN deleted_at IS NULL THEN '' ELSE '（已归档）'"
        " END AS label, '/suts/' || sut_id || '/model?node=' || id AS path FROM model_node"
        " WHERE id = ANY(%(ids)s)",
    ),
    (
        "Field ",
        "SELECT a.id::text AS id, n.name || '.' || a.name AS label,"
        " '/suts/' || a.sut_id || '/model?node=' || n.id AS path FROM entity_attribute a"
        " JOIN model_node n ON n.id=a.node_id WHERE a.id = ANY(%(ids)s)",
    ),
    (
        "Link",
        "SELECT l.id::text AS id, f.name || ' ' || l.forward_name || ' ' || t.name AS label,"
        " '/suts/' || l.sut_id || '/model?view=links' AS path FROM model_link l"
        " JOIN model_node f ON f.id=l.from_node_id JOIN model_node t ON t.id=l.to_node_id"
        " WHERE l.id = ANY(%(ids)s)",
    ),
    (
        "API",
        "SELECT id::text AS id, method || ' ' || path AS label, '/suts/' || sut_id || '/apis'"
        " AS path FROM api_endpoint WHERE id = ANY(%(ids)s)",
    ),
    (
        "Environment",
        "SELECT id::text AS id, '环境 ' || name AS label, '/suts/' || sut_id AS path"
        " FROM environment WHERE id = ANY(%(ids)s)",
    ),
    (
        "Test strategy",
        "SELECT s.id::text AS id, '测试策略 · 版本 ' || v.name AS label,"
        " '/versions/' || v.id || '/strategy' AS path FROM test_strategy s"
        " JOIN version v ON v.id=s.version_id WHERE s.id = ANY(%(ids)s)",
    ),
    (
        "Person",
        "SELECT id::text AS id, name AS label, '/persons' AS path FROM person WHERE id = ANY(%(ids)s)",
    ),
)


def find_uuids(obj) -> list[str]:
    text = json.dumps(obj, ensure_ascii=False, default=str).lower()
    return sorted(set(UUID_RE.findall(text)))


def resolve_refs(db, ids, limit: int = 500) -> dict[str, dict]:
    """{id: {"kind": "Case", "label": "Title (TC-001)", "path": "/cases/…"}}."""
    texts = (str(i).lower() for i in ids if i)
    ids = list(dict.fromkeys(t for t in texts if UUID_RE.fullmatch(t)))[:limit]
    if not ids:
        return {}
    found: dict[str, dict] = {}
    with db.tx() as cur:
        for kind, sql in QUERIES:
            missing = [i for i in ids if i not in found]
            if not missing:
                break
            cur.execute(sql.replace("%(ids)s", "%(ids)s::uuid[]"), {"ids": missing})
            for r in cur.fetchall():
                label = r["label"]
                if kind == "Agent run":
                    label = PURPOSE_LABEL.get(label, label)
                found[r["id"]] = {"kind": kind, "label": label, "path": r["path"]}
    return found


def label_uuids(db, ids: list[str], limit: int = 500) -> dict[str, str]:
    return {k: v["label"] for k, v in resolve_refs(db, ids, limit).items()}


def describe(refs: dict[str, dict], ids) -> str:
    """'Case “Title (TC-001)” · SUT “Procurement (procurement)”' for log lines."""
    parts = []
    for i in dict.fromkeys(str(x).lower() for x in ids):
        ref = refs.get(i)
        if ref:
            parts.append(f"{ref['kind']} “{ref['label']}”")
    return " · ".join(parts)
