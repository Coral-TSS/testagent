"""a read-only review of one SUT's model.

Entities with their fields and relations, relations read both ways, actions with purpose,
inputs/outputs, preconditions/effects and bound APIs; per element the requirements and cases
that touch it (uncovered ones flagged), pending suggestions, and the reviewer's marks. A mark
stores a digest of the element so later changes show as "Changed since review". Marks are a UI aid and
never accept suggestions (C01)."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime

from testagent.core.actor import current_actor
from testagent.core.errors import AppError
from testagent.services.action_rules import effect_text, precondition_text
from testagent.services.changelog import log_change
from testagent.services.links import CARD_TEXT, LinkService, link_text
from testagent.services.navigation import sut_label

FLIP = {"many_to_one": "one_to_many", "one_to_many": "many_to_one"}
TARGETS = ("entity", "action", "link")


def _digest(element: dict) -> str:
    body = {k: v for k, v in element.items() if k not in ("coverage", "uncovered", "mark")}
    raw = json.dumps(body, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def _relation_from(link: dict, node_id: str) -> str:
    if str(link["from_node_id"]) == node_id:
        return link_text(link)
    if str(link["to_node_id"]) == node_id:
        flipped = {**link, "cardinality": FLIP.get(link["cardinality"], link["cardinality"])}
        return link_text(flipped, reverse=True)
    return f"as the junction entity of “{link['from_name']} {link['forward_name']} {link['to_name']}”"


def _param_text(params) -> list[str]:
    out = []
    for p in params or []:
        text = f"{p.get('name')}: {p.get('data_type') or '?'}"
        if p.get("required"):
            text += " (required)"
        if p.get("field"):
            text += f" → {p['field']}"
        out.append(text)
    return out


class ModelReviewService:
    def __init__(self, db, actor: str | None = None):
        self.db = db
        self.actor = actor or current_actor()

    # ------------------------------------------------------------ coverage
    @staticmethod
    def _coverage(cur, sut_id) -> dict[str, dict]:
        cov: dict[str, dict] = {}

        def add(target, kind, row):
            item = cov.setdefault(str(target), {"requirements": [], "cases": []})[kind]
            entry = {k: (str(v) if k.endswith("id") and v else v) for k, v in row.items()}
            if entry not in item:
                item.append(entry)

        req_cols = "r.id, r.code, r.title, r.version_id, v.name AS version_name"
        cur.execute(
            f"SELECT l.node_id AS target, {req_cols} FROM requirement_node_link l"
            " JOIN requirement r ON r.id=l.requirement_id JOIN version v ON v.id=r.version_id"
            " WHERE v.sut_id=%s ORDER BY r.code",
            (sut_id,),
        )
        rows = cur.fetchall()
        cur.execute(
            f"SELECT l.attribute_id AS target, {req_cols} FROM requirement_attribute_link l"
            " JOIN requirement r ON r.id=l.requirement_id JOIN version v ON v.id=r.version_id"
            " WHERE v.sut_id=%s ORDER BY r.code",
            (sut_id,),
        )
        rows += cur.fetchall()
        cur.execute(
            f"SELECT l.link_id AS target, {req_cols} FROM requirement_link_ref l"
            " JOIN requirement r ON r.id=l.requirement_id JOIN version v ON v.id=r.version_id"
            " WHERE v.sut_id=%s ORDER BY r.code",
            (sut_id,),
        )
        rows += cur.fetchall()
        for row in rows:
            target = row.pop("target")
            add(target, "requirements", row)
        case_cols = "c.id, c.code, c.title, c.status"
        live = "c.sut_id=%s AND c.status<>'deprecated'"
        cur.execute(
            f"SELECT l.node_id AS target, {case_cols} FROM case_node_link l"
            f" JOIN test_case c ON c.id=l.case_id WHERE {live} ORDER BY c.code",
            (sut_id,),
        )
        rows = cur.fetchall()
        cur.execute(
            f"SELECT l.attribute_id AS target, {case_cols} FROM case_attribute_link l"
            f" JOIN test_case c ON c.id=l.case_id WHERE {live} ORDER BY c.code",
            (sut_id,),
        )
        rows += cur.fetchall()
        cur.execute(
            f"SELECT DISTINCT x.link_id AS target, {case_cols} FROM requirement_link_ref x"
            " JOIN case_requirement_link l ON l.requirement_id=x.requirement_id"
            f" JOIN test_case c ON c.id=l.case_id WHERE {live} ORDER BY c.code",
            (sut_id,),
        )
        rows += cur.fetchall()
        for row in rows:
            target = row.pop("target")
            add(target, "cases", row)
        return cov

    # ------------------------------------------------------------ review
    def get(self, sut_id) -> dict:
        with self.db.tx() as cur:
            return self._review(cur, sut_id)

    def _review(self, cur, sut_id) -> dict:
        cur.execute("SELECT id, code, name, description FROM sut WHERE id=%s", (sut_id,))
        sut = cur.fetchone()
        if sut is None:
            raise AppError("NOT_FOUND", "SUT not found")
        empty = {"requirements": [], "cases": []}
        cov = self._coverage(cur, sut_id)
        cur.execute(
            "SELECT target_type, target_id::text AS target_id, reviewed, digest, note,"
            " reviewed_by, reviewed_at FROM model_review_mark WHERE sut_id=%s",
            (sut_id,),
        )
        marks = {(r["target_type"], r["target_id"]): r for r in cur.fetchall()}
        links = LinkService.list_rows(cur, sut_id)

        cur.execute(
            "SELECT id::text AS id, kind, name, description, inputs, outputs, input_format,"
            " output_format, preconditions, effects FROM model_node"
            " WHERE sut_id=%s AND deleted_at IS NULL AND kind IN ('entity','action')"
            " ORDER BY kind, created_at",
            (sut_id,),
        )
        nodes = cur.fetchall()
        cur.execute(
            "SELECT a.id::text AS id, a.node_id::text AS node_id, a.name, a.display_name,"
            " a.data_type, a.required, a.enum_values, a.unit, a.format, a.storage_name,"
            " a.description, r.name AS ref_node_name FROM entity_attribute a"
            " LEFT JOIN model_node r ON r.id=a.ref_node_id"
            " WHERE a.sut_id=%s AND a.deleted_at IS NULL ORDER BY a.position, a.created_at",
            (sut_id,),
        )
        fields_by_node: dict[str, list] = {}
        for f in cur.fetchall():
            f["coverage"] = cov.get(f["id"], empty)
            f["uncovered"] = not (f["coverage"]["requirements"] or f["coverage"]["cases"])
            fields_by_node.setdefault(f.pop("node_id"), []).append(f)
        cur.execute(
            "SELECT l.node_id::text AS node_id, a.id::text AS id, a.method, a.path, a.name"
            " FROM node_api_link l JOIN api_endpoint a ON a.id=l.api_id"
            " WHERE a.sut_id=%s ORDER BY a.path, a.method",
            (sut_id,),
        )
        apis: dict[str, list] = {}
        for a in cur.fetchall():
            apis.setdefault(a.pop("node_id"), []).append(a)
        link_names = {str(lk["id"]): link_text(lk) for lk in links}

        def finish(element: dict, kind: str, covered_extra: bool = False) -> dict:
            element["coverage"] = cov.get(element["id"], empty)
            element["uncovered"] = not (
                element["coverage"]["requirements"] or element["coverage"]["cases"] or covered_extra
            )
            mark = marks.get((kind, element["id"]))
            digest = _digest(element)
            element["digest"] = digest
            element["mark"] = (
                {
                    "reviewed": mark["reviewed"],
                    "stale": bool(mark["reviewed"] and mark["digest"] != digest),
                    "note": mark["note"],
                    "reviewed_by": mark["reviewed_by"],
                    "reviewed_at": mark["reviewed_at"],
                }
                if mark
                else None
            )
            return element

        entities, actions = [], []
        for n in nodes:
            if n["kind"] == "entity":
                fields = fields_by_node.get(n["id"], [])
                entity = {
                    "id": n["id"],
                    "name": n["name"],
                    "description": n["description"],
                    "fields": fields,
                    "relations": [
                        _relation_from(lk, n["id"])
                        for lk in links
                        if n["id"] in (str(lk["from_node_id"]), str(lk["to_node_id"]), str(lk["via_node_id"]))
                    ],
                }
                field_covered = any(not f["uncovered"] for f in fields)
                entities.append(finish(entity, "entity", field_covered))
            else:
                action = {
                    "id": n["id"],
                    "name": n["name"],
                    "description": n["description"],
                    "inputs": _param_text(n["inputs"]),
                    "outputs": _param_text(n["outputs"]),
                    "input_format": n["input_format"],
                    "output_format": n["output_format"],
                    "preconditions": [precondition_text(p) for p in n["preconditions"] or []],
                    "effects": [effect_text(e, link_names) for e in n["effects"] or []],
                    "apis": apis.get(n["id"], []),
                }
                actions.append(finish(action, "action"))
        link_items = []
        for lk in links:
            forward = f"{lk['from_name']} {lk['forward_name']} {lk['to_name']}"
            reverse = f"{lk['to_name']} {lk['reverse_name']} {lk['from_name']}"
            extras = link_text(lk)[len(forward) :]
            item = {
                "id": str(lk["id"]),
                "forward": forward,
                "reverse": reverse,
                "text": f"{forward} / {reverse}{extras}",
                "cardinality": CARD_TEXT.get(lk["cardinality"], lk["cardinality"]),
                "fk_field": lk["fk_field"],
                "via_name": lk["via_name"],
                "required": lk["required"],
                "api_names": [x for x in (lk["forward_api_name"], lk["reverse_api_name"]) if x],
                "description": lk["description"],
            }
            link_items.append(finish(item, "link"))

        cur.execute(
            "SELECT kind, count(*) AS n FROM model_suggestion WHERE sut_id=%s AND status='pending' GROUP BY kind",
            (sut_id,),
        )
        by_kind = {r["kind"]: r["n"] for r in cur.fetchall()}
        cur.execute(
            "SELECT source, count(*) AS n FROM model_suggestion WHERE sut_id=%s AND status='pending' GROUP BY source",
            (sut_id,),
        )
        by_source = {r["source"]: r["n"] for r in cur.fetchall()}
        everything = entities + link_items + actions
        marked = [e["mark"] for e in everything if e["mark"] and e["mark"]["reviewed"]]
        return {
            "sut": {
                "id": str(sut["id"]),
                "code": sut["code"],
                "name": sut["name"],
                "description": sut["description"],
            },
            "generated_at": datetime.now().astimezone(),
            "summary": {
                "entities": len(entities),
                "fields": sum(len(e["fields"]) for e in entities),
                "links": len(link_items),
                "actions": len(actions),
                "total": len(everything),
                "reviewed": sum(1 for m in marked if not m["stale"]),
                "stale": sum(1 for m in marked if m["stale"]),
                "uncovered": sum(1 for e in everything if e["uncovered"]),
                "pending_suggestions": sum(by_kind.values()),
            },
            "pending_by_kind": by_kind,
            "pending_by_source": by_source,
            "entities": entities,
            "links": link_items,
            "actions": actions,
        }

    # ------------------------------------------------------------ marks
    def mark(self, sut_id, data: dict) -> dict:
        kind, target = data["target_type"], str(data["target_id"])
        if kind not in TARGETS:
            raise AppError("VALIDATION", "Invalid review target type")
        with self.db.tx() as cur:
            review = self._review(cur, sut_id)
            pool = {
                "entity": review["entities"],
                "action": review["actions"],
                "link": review["links"],
            }
            element = next((e for e in pool[kind] if e["id"] == target), None)
            if element is None:
                raise AppError("NOT_FOUND", "Review target not found")
            reviewed = bool(data.get("reviewed", True))
            note = (data.get("note") or "").strip() or None
            cur.execute(
                "INSERT INTO model_review_mark(sut_id, target_type, target_id, reviewed, digest,"
                " note, reviewed_by) VALUES (%s,%s,%s,%s,%s,%s,%s)"
                " ON CONFLICT (sut_id, target_type, target_id) DO UPDATE SET"
                " reviewed=EXCLUDED.reviewed, digest=EXCLUDED.digest, note=EXCLUDED.note,"
                " reviewed_by=EXCLUDED.reviewed_by, reviewed_at=now() RETURNING *",
                (sut_id, kind, target, reviewed, element["digest"], note, self.actor),
            )
            row = cur.fetchone()
            log_change(
                cur,
                "model_review_mark",
                row["id"],
                "review" if reviewed else "unreview",
                self.actor,
                {"target_type": kind, "target_id": target, "note": note},
            )
            return {**row, "stale": False}

    # ------------------------------------------------------------ markdown
    def markdown(self, sut_id) -> tuple[str, str]:
        r = self.get(sut_id)
        s = r["summary"]
        lines = [
            f"# Model review: {sut_label(r['sut'])}",
            "",
            f"Generated at: {r['generated_at'].strftime('%Y-%m-%d %H:%M')} ",
            f"Review progress: reviewed {s['reviewed']} / {s['total']}; changed since review {s['stale']}; "
            f"not covered by any requirement or case {s['uncovered']}; pending model suggestions "
            f"{s['pending_suggestions']}",
            "",
            "> Review marks only help the review; they do not accept any AI suggestion. Suggestions still have to be "
            "accepted one by one on the version or model page.",
            "",
        ]

        def box(e) -> str:
            m = e["mark"]
            if m and m["reviewed"]:
                return "[x]" if not m["stale"] else "[!]"
            return "[ ]"

        def cov(e) -> str:
            c = e["coverage"]
            parts = []
            if c["requirements"]:
                parts.append("Requirement " + ", ".join(f"{x['title']} ({x['code']})" for x in c["requirements"]))
            if c["cases"]:
                parts.append("Case " + ", ".join(f"{x['title']} ({x['code']})" for x in c["cases"]))
            return "; ".join(parts) if parts else "**Not covered**"

        def note(e) -> list[str]:
            m = e["mark"]
            out = []
            if m and m["stale"]:
                out.append("- Note: changed since review, needs a new review")
            if m and m["note"]:
                out.append(f"- Review note: {m['note']}")
            return out

        lines += ["## Entities", ""]
        if not r["entities"]:
            lines += ["(no entities yet)", ""]
        for e in r["entities"]:
            lines.append(f"### {box(e)} {e['name']}")
            if e["description"]:
                lines.append(e["description"])
            lines.append("")
            if e["fields"]:
                lines += ["| Field | Type | Required | Display name | Description |", "|---|---|---|---|---|"]
                for f in e["fields"]:
                    dtype = f["data_type"]
                    if f["enum_values"]:
                        dtype += " (" + " / ".join(map(str, f["enum_values"])) + ")"
                    if f["ref_node_name"]:
                        dtype += f" → {f['ref_node_name']}"
                    desc = (f["description"] or "").replace("|", "\\|").replace("\n", " ")
                    lines.append(
                        f"| {f['name']} | {dtype} | {'yes' if f['required'] else 'no'} |"
                        f" {f['display_name'] or ''} | {desc} |"
                    )
            else:
                lines.append("(no fields registered)")
            lines.append("")
            for rel in e["relations"]:
                lines.append(f"- Links: {rel}")
            lines.append(f"- Coverage: {cov(e)}")
            lines += note(e) + [""]

        lines += ["## Links", ""]
        if not r["links"]:
            lines += ["(no links yet)", ""]
        for lk in r["links"]:
            lines.append(f"- {box(lk)} {lk['text']} — coverage: {cov(lk)}")
            lines += [f"  {x}" for x in note(lk)]
        lines.append("")

        lines += ["## Actions", ""]
        if not r["actions"]:
            lines += ["(no actions yet)", ""]
        for a in r["actions"]:
            lines.append(f"### {box(a)} {a['name']}")
            lines.append(f"- Purpose: {a['description'] or '(not filled in)'}")
            if a["apis"]:
                lines.append("- API: " + ", ".join(f"{x['method']} {x['path']}" for x in a["apis"]))
            lines.append("- Inputs: " + (", ".join(a["inputs"]) or "(none)"))
            lines.append("- Outputs: " + (", ".join(a["outputs"]) or "(none)"))
            if a["preconditions"]:
                lines.append("- Preconditions: " + "; ".join(a["preconditions"]))
            if a["effects"]:
                lines.append("- Effects: " + "; ".join(a["effects"]))
            lines.append(f"- Coverage: {cov(a)}")
            lines += note(a) + [""]
        filename = f"model-review-{r['sut']['code']}.md"
        return "\n".join(lines).rstrip() + "\n", filename
