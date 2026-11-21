"""End-to-end chains: effect of one action satisfies the next action's precondition."""

from __future__ import annotations

import hashlib
import json

from psycopg.types.json import Jsonb

from testagent.services.case_scope import CaseScopeService
from testagent.services.scope_manifest import derive_chains, prompt_scope


def _dumps(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, default=str)


def _fingerprint(action_ids: list[str]) -> str:
    return hashlib.sha256("|".join(action_ids).encode()).hexdigest()


def chain_tool_scope(graph, chains: list[dict], requirements: list[dict]) -> dict:
    """Objects the end-to-end run may read: the chain's actions, their entities and fields.

    Other actions stay out, so a chain does not become a deeper single-requirement scope.
    """
    action_ids = [a["id"] for chain in chains for a in chain["actions"]]
    entities = set()
    apis = []
    for aid in action_ids:
        action = graph.actions.get(aid)
        if action is None:
            continue
        entities.update(action.actor_ids)
        entities.update(action.object_ids)
        for api_id in action.api_ids:
            api = graph.apis.get(api_id)
            if api:
                apis.append({"id": api.id, "method": api.method, "path": api.path, "origin": "expanded"})
    nodes = [
        {"id": aid, "kind": "action", "name": graph.actions[aid].name, "origin": "seed"}
        for aid in action_ids
        if aid in graph.actions
    ]
    nodes += [
        {"id": eid, "kind": "entity", "name": graph.entities[eid].name, "origin": "expanded"}
        for eid in sorted(entities)
        if eid in graph.entities
    ]
    fields = [
        {"id": f.id, "entity": f.entity, "name": f.name, "origin": "expanded"}
        for f in graph.fields.values()
        if f.entity_id in entities
    ]
    links = []
    for link in graph.links.values():
        if link.from_id in entities and link.to_id in entities:
            links.append(
                {
                    "id": link.id,
                    "name": link.name(),
                    "origin": "expanded",
                    "cardinality": link.cardinality,
                    "required": link.required,
                }
            )
    return {
        "requirement": {"id": requirements[0]["id"], "code": requirements[0]["code"], "title": requirements[0]["title"]}
        if requirements
        else {"id": "", "code": "", "title": ""},
        "depth": 1,
        "nodes": nodes,
        "fields": fields,
        "links": links,
        "apis": apis,
        "targets": [],
        "fingerprint": None,
    }


class ChainService:
    def __init__(self, db):
        self.db = db
        self.scopes = CaseScopeService(db)

    def sync(self, version_id) -> list[dict]:
        with self.db.tx() as cur:
            cur.execute("SELECT * FROM version WHERE id=%s", (version_id,))
            version = cur.fetchone()
            if version is None:
                from testagent.core.errors import AppError

                raise AppError("NOT_FOUND", "Version not found")
            graph = self.scopes.load_graph(cur, version["sut_id"])
            derived = derive_chains(graph)
            cur.execute("SELECT id FROM test_strategy WHERE version_id=%s", (version_id,))
            strategy = cur.fetchone()
            cur.execute(
                "SELECT r.id::text AS id, r.code, r.title, l.node_id::text AS node_id"
                " FROM requirement r JOIN requirement_node_link l ON l.requirement_id=r.id"
                " WHERE r.version_id=%s",
                (version_id,),
            )
            refs = cur.fetchall()
            saved = []
            for chain in derived:
                action_ids = [a["id"] for a in chain["actions"]]
                reqs = []
                seen = set()
                for ref in refs:
                    if ref["node_id"] in action_ids and ref["id"] not in seen:
                        seen.add(ref["id"])
                        reqs.append({"id": ref["id"], "code": ref["code"], "title": ref["title"]})
                reqs.sort(key=lambda r: r["code"])
                fp = _fingerprint(action_ids)
                cur.execute(
                    "INSERT INTO case_gen_chain(version_id, strategy_id, fingerprint, actions,"
                    " transitions, requirement_ids)"
                    " VALUES (%s,%s,%s,%s,%s,%s)"
                    " ON CONFLICT (version_id, fingerprint) DO UPDATE SET strategy_id=EXCLUDED.strategy_id,"
                    " actions=EXCLUDED.actions, transitions=EXCLUDED.transitions,"
                    " requirement_ids=EXCLUDED.requirement_ids RETURNING id::text AS id",
                    (
                        version_id,
                        strategy["id"] if strategy else None,
                        fp,
                        Jsonb(chain["actions"], dumps=_dumps),
                        Jsonb(chain["transitions"], dumps=_dumps),
                        Jsonb(reqs, dumps=_dumps),
                    ),
                )
                row_id = cur.fetchone()["id"]
                transitions = [{**t, "id": t["id"]} for t in chain["transitions"]]
                saved.append(
                    {
                        "id": row_id,
                        "strategy_id": str(strategy["id"]) if strategy else None,
                        "actions": chain["actions"],
                        "transitions": transitions,
                        "requirements": reqs,
                        "targets": [
                            {
                                "id": f"chain:{row_id}",
                                "type": "chain",
                                "actions": [a["name"] for a in chain["actions"]],
                            },
                            *[
                                {
                                    "id": t["id"],
                                    "type": "state_transition",
                                    "from": t["from"],
                                    "to": t["to"],
                                    "when": t["when"],
                                }
                                for t in transitions
                            ],
                        ],
                    }
                )
            return saved

    def tool_scopes(self, version_id, chains: list[dict]) -> list[dict]:
        with self.db.tx() as cur:
            cur.execute("SELECT sut_id FROM version WHERE id=%s", (version_id,))
            sut_id = cur.fetchone()["sut_id"]
            graph = self.scopes.load_graph(cur, sut_id)
        reqs = list({r["id"]: r for chain in chains for r in chain["requirements"]}.values())
        manifest = chain_tool_scope(graph, chains, reqs)
        if not reqs:
            return [prompt_scope(manifest)]
        scopes = []
        for req in reqs:
            copy = {**manifest, "requirement": {"id": req["id"], "code": req["code"], "title": req["title"]}}
            scopes.append(prompt_scope(copy))
        return scopes


def chain_coverage(cur, version_id) -> dict:
    cur.execute(
        "SELECT id::text AS id, actions, transitions FROM case_gen_chain WHERE version_id=%s ORDER BY created_at",
        (version_id,),
    )
    chains = cur.fetchall()
    if not chains:
        return {
            "chains": {"total": 0, "covered": 0, "items": []},
            "state_transitions": {"total": 0, "covered": 0, "items": []},
        }
    cur.execute(
        "SELECT c.id::text AS id, c.code, c.title, c.chain_id::text AS chain_id, c.covers,"
        " coalesce((SELECT array_agg(n.node_id::text) FROM case_node_link n WHERE n.case_id=c.id), '{}') AS nodes"
        " FROM test_case c WHERE c.status <> 'deprecated' AND (c.chain_id IS NOT NULL OR c.origin_version_id=%s)",
        (version_id,),
    )
    cases = cur.fetchall()
    chain_items = []
    transition_items = []
    for chain in chains:
        actions = chain["actions"] or []
        name = " → ".join(a["name"] for a in actions)
        needed = {a["id"] for a in actions}
        hits = []
        for case in cases:
            nodes = set(case["nodes"] or [])
            covers = set(case["covers"] or [])
            linked = case["chain_id"] == chain["id"] or (f"chain:{chain['id']}" in covers and needed <= nodes)
            if linked:
                hits.append({"id": case["id"], "code": case["code"], "title": case["title"]})
        chain_items.append({"id": chain["id"], "name": name, "cases": len(hits), "case_list": hits})
        for step in chain["transitions"] or []:
            step_hits = []
            ends = {step["from_id"], step["to_id"]}
            for case in cases:
                nodes = set(case["nodes"] or [])
                covers = set(case["covers"] or [])
                if step["id"] in covers and ends <= nodes:
                    step_hits.append({"id": case["id"], "code": case["code"], "title": case["title"]})
            transition_items.append(
                {
                    "id": step["id"],
                    "name": f"{step['from']} → {step['to']}",
                    "when": step.get("when"),
                    "cases": len(step_hits),
                    "case_list": step_hits,
                }
            )

    def block(items):
        return {
            "total": len(items),
            "covered": sum(1 for i in items if i["cases"]),
            "uncovered": [{"id": i["id"], "name": i["name"]} for i in items if not i["cases"]],
            "items": items,
        }

    return {"chains": block(chain_items), "state_transitions": block(transition_items)}
