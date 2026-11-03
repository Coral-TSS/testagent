"""Link types between entities (Palantir Ontology style).

A link has two sides: ``from`` reads the link with ``forward_name`` (PurchaseOrder belongs to Supplier) and ``to``
reads it back with ``reverse_name`` (Supplier supplies PurchaseOrder); each side may carry an API name used in
code (supplier / purchaseOrders). The cardinality is one of 1:1, N:1, 1:N, M:N. One-to-one and
many-to-one links are backed by a foreign-key field named like the API/code field (Payment.order_id
→ PurchaseOrder); many-to-many links may be backed by a junction entity with two foreign-key fields.

Links replace the former ``relation`` nodes; ``migrate_relation_nodes`` converts them."""

from __future__ import annotations

import re

from psycopg.types.json import Jsonb

from testagent.core.actor import current_actor
from testagent.core.errors import AppError
from testagent.core.events import EventBus
from testagent.services.changelog import log_change

CARDINALITIES = ("one_to_one", "many_to_one", "one_to_many", "many_to_many")
CARD_TEXT = {"one_to_one": "1:1", "many_to_one": "N:1", "one_to_many": "1:N", "many_to_many": "M:N"}
API_NAME = re.compile(r"^[a-z][A-Za-z0-9_]{0,99}$")
FIELDS = (
    "from_node_id",
    "to_node_id",
    "forward_name",
    "reverse_name",
    "forward_api_name",
    "reverse_api_name",
    "cardinality",
    "fk_attribute_id",
    "via_node_id",
    "via_from_attribute_id",
    "via_to_attribute_id",
    "required",
    "description",
)
SELECT = (
    "SELECT l.*, f.name AS from_name, t.name AS to_name, v.name AS via_name,"
    " (SELECT n.name || '.' || a.name FROM entity_attribute a JOIN model_node n ON n.id=a.node_id"
    "   WHERE a.id=l.fk_attribute_id) AS fk_field,"
    " (SELECT a.name FROM entity_attribute a WHERE a.id=l.via_from_attribute_id) AS via_from_field,"
    " (SELECT a.name FROM entity_attribute a WHERE a.id=l.via_to_attribute_id) AS via_to_field"
    " FROM model_link l JOIN model_node f ON f.id=l.from_node_id"
    " JOIN model_node t ON t.id=l.to_node_id LEFT JOIN model_node v ON v.id=l.via_node_id"
)


def link_text(link: dict, reverse: bool = False) -> str:
    """'PurchaseOrder belongs to Supplier (N:1, foreign key PurchaseOrder.supplier_id)'."""
    if reverse:
        text = f"{link['to_name']} {link['reverse_name']} {link['from_name']}"
    else:
        text = f"{link['from_name']} {link['forward_name']} {link['to_name']}"
    extra = [CARD_TEXT.get(link["cardinality"], link["cardinality"])]
    if link.get("fk_field"):
        extra.append(f"foreign key {link['fk_field']}")
    if link.get("via_name"):
        extra.append(f"junction entity {link['via_name']}")
    return f"{text} ({', '.join(extra)})"


def link_summary(link: dict) -> dict:
    """Compact form for prompts / agent tools."""
    out = {
        "id": str(link["id"]),
        "from": link["from_name"],
        "to": link["to_name"],
        "forward": f"{link['from_name']} {link['forward_name']} {link['to_name']}",
        "reverse": f"{link['to_name']} {link['reverse_name']} {link['from_name']}",
        "cardinality": CARD_TEXT.get(link["cardinality"], link["cardinality"]),
        "required": bool(link.get("required")),
    }
    for key in ("forward_api_name", "reverse_api_name", "fk_field", "via_name", "description"):
        if link.get(key):
            out[key] = link[key]
    if link.get("via_name"):
        out["via_fields"] = [link.get("via_from_field"), link.get("via_to_field")]
    return out


def _singular(word: str) -> str:
    word = word.lower()
    if word.endswith("ies"):
        return word[:-3] + "y"
    if word.endswith("ses") or word.endswith("xes"):
        return word[:-2]
    if word.endswith("s") and not word.endswith("ss"):
        return word[:-1]
    return word


def _camel_plural(stem: str) -> str:
    parts = stem.split("_")
    word = parts[0] + "".join(p.title() for p in parts[1:])
    return word + ("es" if word.endswith("s") else "s")


def resource_stems(cur, sut_id) -> dict[str, str]:
    """{'order': PurchaseOrder id, 'payment': Payment id} from the collection paths of the APIs bound to
    actions acting on an entity (POST/GET …/orders → object entity of the action)."""
    cur.execute(
        "SELECT a.method, a.path, e.target_node_id AS entity_id FROM api_endpoint a"
        " JOIN node_api_link l ON l.api_id=a.id AND l.invalid_at IS NULL"
        " JOIN model_node n ON n.id=l.node_id AND n.kind='action' AND n.deleted_at IS NULL"
        " JOIN model_edge e ON e.source_node_id=n.id AND e.role='object' AND e.invalid_at IS NULL"
        " JOIN model_node t ON t.id=e.target_node_id AND t.kind='entity' AND t.deleted_at IS NULL"
        " WHERE a.sut_id=%s",
        (sut_id,),
    )
    found: dict[str, set] = {}
    for row in cur.fetchall():
        segments = [s for s in row["path"].split("/") if s]
        if not segments or segments[-1].startswith("{") or row["method"] not in ("GET", "POST"):
            continue
        found.setdefault(_singular(segments[-1]), set()).add(str(row["entity_id"]))
    return {stem: next(iter(ids)) for stem, ids in found.items() if len(ids) == 1}


class LinkService:
    def __init__(self, db, bus: EventBus | None, actor: str | None = None):
        self.db = db
        self.bus = bus or EventBus()
        self.actor = actor or current_actor()

    # ------------------------------------------------------------ queries
    @staticmethod
    def list_rows(cur, sut_id, node_id=None, include_deleted=False) -> list[dict]:
        cur.execute(
            SELECT + " WHERE l.sut_id=%s AND (%s OR l.deleted_at IS NULL)"
            " AND (%s::uuid IS NULL OR %s::uuid IN (l.from_node_id, l.to_node_id, l.via_node_id))"
            " ORDER BY f.name, t.name, l.forward_name",
            (sut_id, include_deleted, node_id, node_id),
        )
        return cur.fetchall()

    @staticmethod
    def list_rows_for_node(cur, node_id) -> list[dict]:
        cur.execute(
            SELECT + " WHERE l.deleted_at IS NULL AND %s::uuid IN (l.from_node_id, l.to_node_id, l.via_node_id)",
            (node_id,),
        )
        return cur.fetchall()

    def list(self, sut_id, node_id=None) -> list[dict]:
        with self.db.tx() as cur:
            return self.list_rows(cur, sut_id, node_id)

    @staticmethod
    def _get(cur, link_id, lock=False) -> dict:
        cur.execute(SELECT + " WHERE l.id=%s", (link_id,))
        row = cur.fetchone()
        if row is None or row["deleted_at"] is not None:
            raise AppError("NOT_FOUND", "Link not found")
        if lock:
            cur.execute("SELECT 1 FROM model_link WHERE id=%s FOR UPDATE", (link_id,))
        return row

    def get(self, link_id) -> dict:
        with self.db.tx() as cur:
            row = self._get(cur, link_id)
            row["references"] = self._references(cur, link_id)
            return row

    @staticmethod
    def _references(cur, link_id) -> list[dict]:
        cur.execute(
            "SELECT DISTINCT 'requirement' AS type, r.id, r.code AS label"
            " FROM requirement_link_ref x JOIN requirement r ON r.id=x.requirement_id"
            " WHERE x.link_id=%s"
            " UNION ALL SELECT 'action', n.id, n.name FROM model_node n WHERE n.deleted_at IS NULL"
            " AND EXISTS (SELECT 1 FROM jsonb_array_elements(n.effects) e"
            "   WHERE e->>'link_id' = %s::text)",
            (link_id, str(link_id)),
        )
        return cur.fetchall()

    # ------------------------------------------------------------ validation
    @staticmethod
    def _entity(cur, sut_id, node_id, field: str) -> dict:
        cur.execute("SELECT id, sut_id, kind, name, deleted_at FROM model_node WHERE id=%s", (node_id,))
        row = cur.fetchone()
        if row is None or row["deleted_at"] is not None or str(row["sut_id"]) != str(sut_id):
            raise AppError("VALIDATION", "Entity not found", field_errors=[{"field": field}])
        if row["kind"] != "entity":
            raise AppError("VALIDATION", "Links can only connect entities", field_errors=[{"field": field}])
        return row

    @staticmethod
    def _attr(cur, attr_id, owners: list, field: str, what: str) -> dict:
        cur.execute(
            "SELECT id, node_id, name, data_type, ref_node_id FROM entity_attribute WHERE id=%s AND deleted_at IS NULL",
            (attr_id,),
        )
        row = cur.fetchone()
        if row is None:
            raise AppError("VALIDATION", "Field not found", field_errors=[{"field": field}])
        if str(row["node_id"]) not in {str(o) for o in owners}:
            raise AppError("VALIDATION", what, field_errors=[{"field": field}])
        return row

    @staticmethod
    def _ref_field(cur, owner, target) -> str | None:
        """The single reference-type field of `owner` that points at `target`."""
        cur.execute(
            "SELECT id FROM entity_attribute WHERE node_id=%s AND deleted_at IS NULL"
            " AND data_type='reference' AND ref_node_id=%s",
            (owner, target),
        )
        rows = cur.fetchall()
        return str(rows[0]["id"]) if len(rows) == 1 else None

    def _validate(self, cur, sut_id, link: dict, link_id=None) -> dict:
        for key in ("forward_name", "reverse_name"):
            link[key] = (link.get(key) or "").strip()
            if not link[key]:
                raise AppError("VALIDATION", "Both side names of a link are required", field_errors=[{"field": key}])
            if len(link[key]) > 50:
                raise AppError("VALIDATION", "Names cannot exceed 50 characters", field_errors=[{"field": key}])
        for key in ("forward_api_name", "reverse_api_name"):
            link[key] = (link.get(key) or "").strip() or None
            if link[key] and not API_NAME.match(link[key]):
                raise AppError(
                    "VALIDATION",
                    "API names must start with a lowercase letter and contain only letters, digits and underscores",
                    field_errors=[{"field": key}],
                )
        if link.get("cardinality") not in CARDINALITIES:
            raise AppError("VALIDATION", "Unknown cardinality", field_errors=[{"field": "cardinality"}])
        src = self._entity(cur, sut_id, link["from_node_id"], "from_node_id")
        dst = self._entity(cur, sut_id, link["to_node_id"], "to_node_id")
        card = link["cardinality"]
        if card == "many_to_many":
            if link.get("fk_attribute_id"):
                raise AppError(
                    "VALIDATION",
                    "A many-to-many link has no single foreign key; use a junction entity",
                    field_errors=[{"field": "fk_attribute_id"}],
                )
        else:
            for key in ("via_node_id", "via_from_attribute_id", "via_to_attribute_id"):
                if link.get(key):
                    raise AppError(
                        "VALIDATION",
                        "Only many-to-many links can have a junction entity",
                        field_errors=[{"field": key}],
                    )
            owners = {
                "many_to_one": [src["id"]],
                "one_to_many": [dst["id"]],
                "one_to_one": [src["id"], dst["id"]],
            }[card]
            if link.get("fk_attribute_id"):
                self._attr(
                    cur,
                    link["fk_attribute_id"],
                    owners,
                    "fk_attribute_id",
                    "The foreign-key field must be on the “many” side (the source for N:1, the target for 1:N)",
                )
            elif "fk_attribute_id" not in link or link.get("_auto_fk"):
                owner, target = (src["id"], dst["id"]) if card != "one_to_many" else (dst["id"], src["id"])
                link["fk_attribute_id"] = self._ref_field(cur, owner, target)
        if link.get("via_node_id"):
            via = self._entity(cur, sut_id, link["via_node_id"], "via_node_id")
            for key, end in (("via_from_attribute_id", src), ("via_to_attribute_id", dst)):
                if not link.get(key):
                    link[key] = self._ref_field(cur, via["id"], end["id"])
                if not link.get(key):
                    raise AppError(
                        "VALIDATION",
                        f"Junction entity “{via['name']}“ needs a foreign-key field pointing to “{end['name']}” ",
                        field_errors=[{"field": key}],
                    )
                self._attr(
                    cur,
                    link[key],
                    [via["id"]],
                    key,
                    "The junction entity's foreign-key fields must belong to the junction entity",
                )
        elif link.get("via_from_attribute_id") or link.get("via_to_attribute_id"):
            raise AppError("VALIDATION", "Choose the junction entity first", field_errors=[{"field": "via_node_id"}])
        # API names exposed on an entity must be unique (Palantir: per object type)
        exposed = [
            (link["from_node_id"], link["forward_api_name"], "forward_api_name"),
            (link["to_node_id"], link["reverse_api_name"], "reverse_api_name"),
        ]
        if (
            link["forward_api_name"]
            and str(link["from_node_id"]) == str(link["to_node_id"])
            and link["forward_api_name"] == link["reverse_api_name"]
        ):
            raise AppError(
                "CONFLICT",
                "The two API names of a self-link must differ",
                field_errors=[{"field": "reverse_api_name"}],
            )
        for node_id, api_name, key in exposed:
            if not api_name:
                continue
            cur.execute(
                "SELECT 1 FROM model_link WHERE deleted_at IS NULL"
                " AND (%s::uuid IS NULL OR id<>%s::uuid) AND ((from_node_id=%s"
                " AND forward_api_name=%s) OR (to_node_id=%s AND reverse_api_name=%s))",
                (link_id, link_id, node_id, api_name, node_id, api_name),
            )
            if cur.fetchone():
                raise AppError(
                    "CONFLICT", f"This entity already has a link named {api_name} ", field_errors=[{"field": key}]
                )
        cur.execute(
            "SELECT 1 FROM model_link WHERE deleted_at IS NULL"
            " AND (%s::uuid IS NULL OR id<>%s::uuid) AND from_node_id=%s AND to_node_id=%s"
            " AND forward_name=%s",
            (link_id, link_id, link["from_node_id"], link["to_node_id"], link["forward_name"]),
        )
        if cur.fetchone():
            raise AppError(
                "CONFLICT",
                f"A link already exists: “{src['name']} {link['forward_name']} {dst['name']}”",
                field_errors=[{"field": "forward_name"}],
            )
        link["required"] = bool(link.get("required"))
        link["description"] = (link.get("description") or "").strip() or None
        return link

    # ------------------------------------------------------------ writes
    def create(self, sut_id, data: dict, cur=None) -> dict:
        if cur is None:
            with self.db.tx() as c:
                row = self.create(sut_id, data, cur=c)
            self.bus.publish("model_link.created", {"id": str(row["id"]), "sut_id": str(sut_id)})
            return row
        link = {k: data.get(k) for k in FIELDS if k in data}
        link.setdefault("required", False)
        link = self._validate(cur, sut_id, {**link, "_auto_fk": not data.get("fk_attribute_id")})
        link.pop("_auto_fk", None)
        values = {k: (str(v) if k.endswith("_id") and v else v) for k, v in link.items()}
        cols = ", ".join(values)
        cur.execute(
            f"INSERT INTO model_link(sut_id, legacy_node_id, {cols})"
            f" VALUES (%s, %s, {', '.join(['%s'] * len(values))}) RETURNING id",
            (sut_id, data.get("legacy_node_id"), *values.values()),
        )
        link_id = cur.fetchone()["id"]
        log_change(cur, "model_link", link_id, "create", self.actor, values)
        return self._get(cur, link_id)

    def update(self, link_id, data: dict) -> dict:
        with self.db.tx() as cur:
            current = self._get(cur, link_id, lock=True)
            merged = {k: current[k] for k in FIELDS}
            merged.update({k: data[k] for k in FIELDS if k in data})
            if merged["cardinality"] == "many_to_many":
                merged["fk_attribute_id"] = None
            else:
                for key in ("via_node_id", "via_from_attribute_id", "via_to_attribute_id"):
                    merged[key] = None
            if "via_node_id" in data and str(data.get("via_node_id")) != str(current["via_node_id"]):
                for key in ("via_from_attribute_id", "via_to_attribute_id"):
                    merged[key] = data.get(key)
            merged = self._validate(cur, current["sut_id"], merged, link_id)
            values = {k: (str(v) if k.endswith("_id") and v else v) for k, v in merged.items()}
            changed = {k: v for k, v in values.items() if _differs(v, current[k])}
            if changed:
                sets = ", ".join(f"{k}=%s" for k in changed)
                cur.execute(f"UPDATE model_link SET {sets} WHERE id=%s", (*changed.values(), link_id))
                log_change(cur, "model_link", link_id, "update", self.actor, changed)
            row = self._get(cur, link_id)
        self.bus.publish("model_link.updated", {"id": str(link_id)})
        return row

    def delete(self, link_id, *, confirm: bool = False) -> dict:
        with self.db.tx() as cur:
            self._get(cur, link_id, lock=True)
            refs = self._references(cur, link_id)
            if refs and not confirm:
                raise AppError(
                    "CONFLICT",
                    f"This link is still referenced by {len(refs)} item(s); confirm to delete",
                    related=[f"{r['type']}:{r['id']}:{r['label']}" for r in refs],
                )
            cur.execute("UPDATE model_link SET deleted_at=now() WHERE id=%s", (link_id,))
            log_change(cur, "model_link", link_id, "soft_delete", self.actor, {"refs": len(refs)})
        self.bus.publish("model_link.deleted", {"id": str(link_id)})
        return {"deleted": True, "references": refs}


def _differs(new, old) -> bool:
    return (None if new is None else str(new)) != (None if old is None else str(old))


# ---------------------------------------------------------------- suggestions
def link_suggestions(cur, sut_id) -> list[dict]:
    """Pending-suggestion payloads for links implied by fields: a reference-type field
    (Payment.order_id → PurchaseOrder) or a ``<resource>_id`` field whose resource is the collection of
    another entity's APIs (order_id ↔ POST /orders → PurchaseOrder). Fields already backing a link and
    entity pairs already linked are skipped."""
    from testagent.services.attributes import AttributeService

    fields = AttributeService(None, None).list_for_sut(sut_id, cur=cur)
    links = LinkService.list_rows(cur, sut_id)
    used = {
        str(x)
        for lk in links
        for x in (lk["fk_attribute_id"], lk["via_from_attribute_id"], lk["via_to_attribute_id"])
        if x
    }
    pairs = {frozenset((str(lk["from_node_id"]), str(lk["to_node_id"]))) for lk in links}
    cur.execute(
        "SELECT id::text AS id, name FROM model_node WHERE sut_id=%s AND kind='entity' AND deleted_at IS NULL",
        (sut_id,),
    )
    entities = {r["id"]: r["name"] for r in cur.fetchall()}
    stems = resource_stems(cur, sut_id)
    owner_stem = {v: k for k, v in stems.items()}
    out = []
    for f in fields:
        owner = str(f["node_id"])
        if owner not in entities or str(f["id"]) in used or f["name"].lower() == "id":
            continue
        name = f["name"].lower()
        stem = name[:-3] if name.endswith("_id") else None
        if f["data_type"] == "reference" and f.get("ref_node_id"):
            target = str(f["ref_node_id"])
            why = f"Field {f['node_name']}.{f['name']} has type “reference”, points to “{entities.get(target)}”"
        elif stem and stem in stems:
            target = stems[stem]
            why = (
                f"Field {f['node_name']}.{f['name']} matches “{entities.get(target)}” API resource"
                f" {stem} by name (…/{stem}s)"
            )
        else:
            continue
        if target not in entities or target == owner:
            continue
        pair = frozenset((owner, target))
        if pair in pairs:
            continue
        pairs.add(pair)
        reverse_stem = owner_stem.get(owner)
        out.append(
            {
                "kind": "link",
                "from_node_id": owner,
                "to_node_id": target,
                "from_name": entities[owner],
                "to_name": entities[target],
                "forward_name": "belongs to",
                "reverse_name": "has",
                "forward_api_name": stem if stem and API_NAME.match(stem) else None,
                "reverse_api_name": (
                    _camel_plural(reverse_stem)
                    if reverse_stem and API_NAME.match(_camel_plural(reverse_stem))
                    else None
                ),
                "cardinality": "many_to_one",
                "fk_attribute_id": str(f["id"]),
                "fk_field": f"{f['node_name']}.{f['name']}",
                "reason": why
                + "; suggest a many-to-one link, please confirm the names on both sides (preposition/verb)",
            }
        )
    return out


def suggest_links(db, bus, sut_id) -> list[dict]:
    """Store the link suggestions (pending, de-duplicated); returns the created rows."""
    from testagent.services.suggestions import SuggestionService

    with db.tx() as cur:
        return SuggestionService(db, bus).add_many(cur, sut_id, link_suggestions(cur, sut_id))


# ---------------------------------------------------------------- relation nodes → links
def migrate_relation_nodes(cur, actor: str = "migration", sut_id=None) -> list[dict]:
    """Convert every active relation node (source/target edges) into a link, carry its
    requirement references over, then archive the node (soft delete + edges invalidated).
    Names default to related/related (to be renamed by a person); idempotent."""
    cur.execute(
        "SELECT n.id, n.sut_id, n.name, n.description,"
        " (SELECT target_node_id FROM model_edge WHERE source_node_id=n.id AND role='source'"
        "   AND invalid_at IS NULL LIMIT 1) AS from_id,"
        " (SELECT target_node_id FROM model_edge WHERE source_node_id=n.id AND role='target'"
        "   AND invalid_at IS NULL LIMIT 1) AS to_id"
        " FROM model_node n WHERE n.kind='relation' AND n.deleted_at IS NULL"
        " AND (%s::uuid IS NULL OR n.sut_id=%s::uuid) ORDER BY n.created_at",
        (sut_id, sut_id),
    )
    service = LinkService(None, None, actor)
    done = []
    for rel in cur.fetchall():
        link = None
        if rel["from_id"] and rel["to_id"]:
            cur.execute(
                "SELECT count(*) AS n FROM model_node WHERE id IN (%s,%s) AND kind='entity' AND deleted_at IS NULL",
                (rel["from_id"], rel["to_id"]),
            )
            if cur.fetchone()["n"] == (1 if rel["from_id"] == rel["to_id"] else 2):
                link = service.create(
                    rel["sut_id"],
                    {
                        "from_node_id": rel["from_id"],
                        "to_node_id": rel["to_id"],
                        "forward_name": "related",
                        "reverse_name": "related",
                        "cardinality": "many_to_one",
                        "description": rel["description"] or f"Migrated from link node “{rel['name']}”",
                        "legacy_node_id": rel["id"],
                    },
                    cur=cur,
                )
        if link is not None:
            cur.execute(
                "INSERT INTO requirement_link_ref(requirement_id, link_id, role)"
                " SELECT requirement_id, %s, role FROM requirement_node_link WHERE node_id=%s"
                " ON CONFLICT DO NOTHING",
                (link["id"], rel["id"]),
            )
            _repoint_structures(cur, rel["id"], link)
        cur.execute("UPDATE model_node SET deleted_at=now() WHERE id=%s", (rel["id"],))
        cur.execute(
            "UPDATE model_edge SET invalid_at=now() WHERE (source_node_id=%(n)s"
            " OR target_node_id=%(n)s) AND invalid_at IS NULL",
            {"n": rel["id"]},
        )
        log_change(
            cur,
            "model_node",
            rel["id"],
            "archive_relation",
            actor,
            {"link_id": str(link["id"]) if link else None, "name": rel["name"]},
        )
        done.append({"relation": rel["name"], "link": link})
    return done


def _repoint_structures(cur, relation_id, link: dict) -> None:
    """Planning requirements whose structured items point at the relation node now point at the
    link (node_id = the link's from entity)."""
    cur.execute(
        "SELECT r.id, r.structured FROM requirement r JOIN version v ON v.id=r.version_id"
        " WHERE v.status='planning' AND EXISTS (SELECT 1 FROM requirement_node_link l"
        "   WHERE l.requirement_id=r.id AND l.node_id=%s) FOR UPDATE OF r",
        (relation_id,),
    )
    for req in cur.fetchall():
        structured = req["structured"] or {}
        changed = False
        for part, items in structured.items():
            if not isinstance(items, list):
                continue
            for item in items:
                if isinstance(item, dict) and str(item.get("node_id")) == str(relation_id):
                    item["node_id"] = str(link["from_node_id"])
                    item["link_id"] = str(link["id"])
                    changed = True
                    cur.execute(
                        "INSERT INTO requirement_node_link(requirement_id, node_id, role)"
                        " VALUES (%s,%s,%s) ON CONFLICT DO NOTHING",
                        (req["id"], link["from_node_id"], part),
                    )
        if changed:
            cur.execute("UPDATE requirement SET structured=%s WHERE id=%s", (Jsonb(structured), req["id"]))
