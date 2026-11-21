"""Deterministic per-requirement scope (design: case-generation-scope-coverage).

The same requirement, model and depth always yield the same manifest. Depth 0 is the
seed only. Depth 1 adds one hop and still obeys the edges that are never walked:
``ref`` edges, downstream actions (effect → another action's precondition), read-only
list actions, and any further hop from a link's far-side entity. Depth 2 takes one
more hop under the same bans. Raising depth never pulls an end-to-end chain.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field

from testagent.services.action_rules import effect_text, precondition_text

READ_ONLY_NAME = re.compile(r"^(list|get|query|search|read|view|列出|查询|查看)\b", re.IGNORECASE)
SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
STATE_FIELDS = frozenset({"status", "state"})
CARD_TEXT = {
    "one_to_one": "1:1",
    "many_to_one": "N:1",
    "one_to_many": "1:N",
    "many_to_many": "M:N",
}
CARD_BOUNDARY = {
    "one_to_one": "1:1 的一端已被占用",
    "many_to_one": "N:1 的 N 侧有多个对象",
    "one_to_many": "1:N 的 N 侧有多个对象",
    "many_to_many": "M:N 两侧都有多个对象",
}
MISSING_REFS = "没有结构化引用（节点、字段或链接）。请先在需求上挂上模型对象后再生成用例。"


@dataclass
class FieldRec:
    id: str
    entity_id: str
    entity: str
    name: str
    required: bool = False


@dataclass
class LinkRec:
    id: str
    from_id: str
    to_id: str
    from_name: str
    to_name: str
    forward_name: str
    cardinality: str
    required: bool = False
    fk_attribute_id: str | None = None

    def name(self) -> str:
        return f"{self.from_name} {self.forward_name} {self.to_name}"

    def ends(self) -> tuple[str, str]:
        return (self.from_id, self.to_id)


@dataclass
class ApiRec:
    id: str
    method: str
    path: str
    action_id: str


@dataclass
class ActionRec:
    id: str
    name: str
    preconditions: list[dict] = field(default_factory=list)
    effects: list[dict] = field(default_factory=list)
    inputs: list[dict] = field(default_factory=list)
    outputs: list[dict] = field(default_factory=list)
    actor_ids: list[str] = field(default_factory=list)
    object_ids: list[str] = field(default_factory=list)
    ref_ids: list[str] = field(default_factory=list)
    api_ids: list[str] = field(default_factory=list)
    read_only: bool = False


@dataclass
class EntityRec:
    id: str
    name: str
    states: list[str] = field(default_factory=list)
    constraints: list[str] = field(default_factory=list)


@dataclass
class Graph:
    entities: dict[str, EntityRec] = field(default_factory=dict)
    fields: dict[str, FieldRec] = field(default_factory=dict)
    actions: dict[str, ActionRec] = field(default_factory=dict)
    links: dict[str, LinkRec] = field(default_factory=dict)
    apis: dict[str, ApiRec] = field(default_factory=dict)
    fields_by_entity: dict[str, list[str]] = field(default_factory=dict)
    links_by_entity: dict[str, list[str]] = field(default_factory=dict)
    links_by_field: dict[str, list[str]] = field(default_factory=dict)
    actions_by_entity: dict[str, list[str]] = field(default_factory=dict)
    actions_by_field: dict[str, list[str]] = field(default_factory=dict)
    downstream_of: dict[str, set[str]] = field(default_factory=dict)
    globally_downstream: set[str] = field(default_factory=set)


@dataclass
class Item:
    kind: str
    id: str
    origin: str
    hop: int
    expandable: bool
    far_side: bool = False
    cover: bool = True
    name: str = ""


@dataclass
class RequirementRefs:
    id: str
    code: str
    title: str
    nodes: list[tuple[str, str]] = field(default_factory=list)
    """(node_id, role) for live entity or action nodes."""
    fields: list[tuple[str, str]] = field(default_factory=list)
    """(attribute_id, role)."""
    links: list[tuple[str, str]] = field(default_factory=list)
    """(link_id, role)."""

    def has_refs(self) -> bool:
        return bool(self.nodes or self.fields or self.links)


def _texts(raw) -> list[str]:
    out = []
    for item in raw or []:
        if isinstance(item, dict):
            text = str(item.get("text") or item.get("expr") or "").strip()
        else:
            text = str(item).strip()
        if text:
            out.append(text)
    return out


def entity_states(attributes: dict | None) -> list[str]:
    return _texts((attributes or {}).get("states"))


def entity_constraints(attributes: dict | None) -> list[str]:
    return _texts((attributes or {}).get("constraints"))


def action_is_read_only(name: str, methods: set[str], *, has_effects: bool, has_preconditions: bool) -> bool:
    """A query action (for example "List payments") is not part of a requirement's scope
    unless the requirement cites it. An action with effects or preconditions is not a query."""
    if has_effects or has_preconditions:
        return False
    if methods and methods <= SAFE_METHODS:
        return True
    return bool(READ_ONLY_NAME.match(name.strip()))


def _same_field(left: dict, right: dict) -> bool:
    left_id = str(left.get("attribute_id") or "")
    right_id = str(right.get("attribute_id") or "")
    if left_id and right_id:
        return left_id == right_id
    left_name = left.get("field") or ""
    right_name = right.get("field") or ""
    return bool(left_name and left_name == right_name)


def effect_enables(effect: dict, pre: dict) -> bool:
    """True when an effect writes a value that satisfies another action's precondition."""
    if (effect.get("kind") or "set_field") != "set_field":
        return False
    if not _same_field(effect, pre):
        return False
    written = {str(v) for v in (effect.get("values") or [])}
    op = pre.get("op") or "eq"
    if op == "eq" and pre.get("value") is not None:
        return str(pre["value"]) in written
    if op == "in" and isinstance(pre.get("value"), list):
        return bool(written & {str(v) for v in pre["value"]})
    return False


def index_graph(graph: Graph) -> Graph:
    """Fill the lookup maps. Safe to call more than once."""
    graph.fields_by_entity = {}
    graph.links_by_entity = {}
    graph.links_by_field = {}
    graph.actions_by_entity = {}
    graph.actions_by_field = {}
    graph.downstream_of = {}
    labels = {f"{f.entity}.{f.name}": f.id for f in graph.fields.values()}
    for f in graph.fields.values():
        graph.fields_by_entity.setdefault(f.entity_id, []).append(f.id)
    for fids in graph.fields_by_entity.values():
        fids.sort(key=lambda i: graph.fields[i].name)
    for link in graph.links.values():
        graph.links_by_entity.setdefault(link.from_id, []).append(link.id)
        graph.links_by_entity.setdefault(link.to_id, []).append(link.id)
        if link.fk_attribute_id:
            graph.links_by_field.setdefault(link.fk_attribute_id, []).append(link.id)
    for action in graph.actions.values():
        for eid in (*action.actor_ids, *action.object_ids):
            graph.actions_by_entity.setdefault(eid, []).append(action.id)
        for attr in _mentioned(action, labels):
            graph.actions_by_field.setdefault(attr, []).append(action.id)
    for aids in graph.actions_by_entity.values():
        aids.sort(key=lambda i: graph.actions[i].name)
    for source in graph.actions.values():
        enabled = set()
        for other in graph.actions.values():
            if other.id == source.id:
                continue
            if any(effect_enables(e, p) for e in source.effects for p in other.preconditions):
                enabled.add(other.id)
        graph.downstream_of[source.id] = enabled
    graph.globally_downstream = {aid for enabled in graph.downstream_of.values() for aid in enabled}
    return graph


def _mentioned(action: ActionRec, labels: dict[str, str]) -> set[str]:
    found = set()
    blobs = [*action.preconditions, *action.effects, *action.inputs, *action.outputs]
    for blob in blobs:
        if blob.get("attribute_id"):
            found.add(str(blob["attribute_id"]))
        label = blob.get("field")
        if label and label in labels:
            found.add(labels[label])
    return found


def _bind_labels(graph: Graph, action: ActionRec) -> None:
    """Copy attribute ids onto rules that only named Entity.field, so chain matching is stable."""
    labels = {f"{f.entity}.{f.name}": f.id for f in graph.fields.values()}
    for blob in (*action.preconditions, *action.effects, *action.inputs, *action.outputs):
        if not blob.get("attribute_id") and blob.get("field") in labels:
            blob["attribute_id"] = labels[blob["field"]]


def prepare(graph: Graph) -> Graph:
    for action in graph.actions.values():
        _bind_labels(graph, action)
        methods = {graph.apis[i].method.upper() for i in action.api_ids if i in graph.apis}
        action.read_only = action_is_read_only(
            action.name,
            methods,
            has_effects=bool(action.effects),
            has_preconditions=bool(action.preconditions),
        )
    return index_graph(graph)


class _Walk:
    def __init__(self, graph: Graph, depth: int):
        self.graph = graph
        self.depth = depth
        self.included: dict[tuple[str, str], Item] = {}
        self.queue: list[tuple[str, str]] = []
        self.expanded: set[tuple[str, str]] = set()
        self.seeds: set[str] = set()

    def add(
        self,
        kind: str,
        id_: str,
        *,
        origin: str,
        hop: int,
        expandable: bool,
        far_side: bool = False,
        cover: bool = True,
        name: str = "",
    ) -> Item:
        key = (kind, id_)
        current = self.included.get(key)
        if current is not None:
            if origin == "seed" and current.origin != "seed":
                current.origin = "seed"
                current.hop = 0
                current.expandable = True
                current.far_side = False
                current.cover = True
                if key not in self.expanded and self.depth > 0:
                    self.queue.append(key)
            return current
        item = Item(kind, id_, origin, hop, expandable, far_side, cover, name)
        self.included[key] = item
        if expandable and hop < self.depth:
            self.queue.append(key)
        return item

    def _core(self, entity_id: str) -> bool:
        item = self.included.get(("node", entity_id))
        return item is not None and not item.far_side

    def add_far_entity(self, entity_id: str, hop: int) -> None:
        if entity_id not in self.graph.entities or self._core(entity_id):
            return
        entity = self.graph.entities[entity_id]
        self.add("node", entity_id, origin="expanded", hop=hop, expandable=False, far_side=True, name=entity.name)
        for fid in self.graph.fields_by_entity.get(entity_id, []):
            field_rec = self.graph.fields[fid]
            self.add(
                "field",
                fid,
                origin="expanded",
                hop=hop,
                expandable=False,
                far_side=True,
                name=field_rec.name,
            )

    def include_link(self, link: LinkRec, hop: int, origin: str, near_ids: set[str]) -> None:
        self.add("link", link.id, origin=origin, hop=hop, expandable=False, name=link.name())
        near = [end for end in link.ends() if end in near_ids or self._core(end)]
        for end in link.ends():
            if end in near:
                if ("node", end) not in self.included and end in self.graph.entities:
                    self.add(
                        "node",
                        end,
                        origin=origin,
                        hop=hop,
                        expandable=hop < self.depth,
                        name=self.graph.entities[end].name,
                    )
            else:
                self.add_far_entity(end, hop)

    def maybe_action(self, action_id: str, hop: int) -> None:
        action = self.graph.actions.get(action_id)
        if action is None or action_id in self.seeds:
            return
        if ("node", action_id) in self.included:
            return
        if action.read_only:
            return
        if action_id in self.graph.globally_downstream:
            return
        included_actions = {i for kind, i in self.included if kind == "node" and i in self.graph.actions}
        if self.graph.downstream_of.get(action_id, set()) & included_actions:
            return  # upstream of an action already in scope; the chain is end-to-end, not this requirement
        self.add("node", action_id, origin="expanded", hop=hop, expandable=True, name=action.name)

    def expand_entity(self, entity_id: str, hop: int) -> None:
        entity = self.graph.entities.get(entity_id)
        if entity is None:
            return
        nxt = hop + 1
        for fid in self.graph.fields_by_entity.get(entity_id, []):
            rec = self.graph.fields[fid]
            self.add("field", fid, origin="expanded", hop=nxt, expandable=False, name=rec.name)
        for index, text in enumerate(entity.constraints):
            self.add(
                "constraint",
                f"{entity_id}:{index}",
                origin="expanded",
                hop=nxt,
                expandable=False,
                name=text,
            )
        for action_id in self.graph.actions_by_entity.get(entity_id, []):
            self.maybe_action(action_id, nxt)
        near = {entity_id}
        for link_id in self.graph.links_by_entity.get(entity_id, []):
            self.include_link(self.graph.links[link_id], nxt, "expanded", near)

    def expand_field(self, field_id: str, hop: int) -> None:
        rec = self.graph.fields.get(field_id)
        if rec is None:
            return
        nxt = hop + 1
        for action_id in self.graph.actions_by_field.get(field_id, []):
            self.maybe_action(action_id, nxt)
        for link_id in self.graph.links_by_field.get(field_id, []):
            self.include_link(self.graph.links[link_id], nxt, "expanded", {rec.entity_id})

    def expand_action(self, action_id: str, hop: int) -> None:
        action = self.graph.actions.get(action_id)
        if action is None:
            return
        nxt = hop + 1
        labels = {f"{f.entity}.{f.name}": f.id for f in self.graph.fields.values()}
        for api_id in action.api_ids:
            api = self.graph.apis.get(api_id)
            if api is None:
                continue
            self.add("api", api_id, origin="expanded", hop=nxt, expandable=False, name=f"{api.method} {api.path}")
        for fid in _mentioned(action, labels):
            rec = self.graph.fields.get(fid)
            if rec is None:
                continue
            self.add("field", fid, origin="expanded", hop=nxt, expandable=False, name=rec.name)
            if rec.entity_id in self.graph.entities and ("node", rec.entity_id) not in self.included:
                ent = self.graph.entities[rec.entity_id]
                self.add("node", rec.entity_id, origin="expanded", hop=nxt, expandable=True, name=ent.name)
        near = set(action.actor_ids) | set(action.object_ids)
        for eid in near:
            if eid in self.graph.entities and ("node", eid) not in self.included:
                ent = self.graph.entities[eid]
                self.add("node", eid, origin="expanded", hop=nxt, expandable=True, name=ent.name)
        for effect in action.effects:
            link_id = str(effect.get("link_id") or "")
            if link_id in self.graph.links:
                self.include_link(self.graph.links[link_id], nxt, "expanded", near)
            node_id = str(effect.get("node_id") or "")
            if node_id in self.graph.entities and ("node", node_id) not in self.included:
                ent = self.graph.entities[node_id]
                self.add("node", node_id, origin="expanded", hop=nxt, expandable=True, name=ent.name)

    def expand_link(self, link_id: str, hop: int) -> None:
        link = self.graph.links.get(link_id)
        if link is None:
            return
        self.include_link(link, hop + 1, "expanded", set())

    def expand(self, item: Item) -> None:
        if item.kind == "node" and item.id in self.graph.entities:
            self.expand_entity(item.id, item.hop)
        elif item.kind == "node" and item.id in self.graph.actions:
            self.expand_action(item.id, item.hop)
        elif item.kind == "field":
            self.expand_field(item.id, item.hop)
        elif item.kind == "link":
            self.expand_link(item.id, item.hop)

    def run(self) -> None:
        while self.queue:
            key = self.queue.pop(0)
            if key in self.expanded:
                continue
            item = self.included.get(key)
            if item is None or not item.expandable or item.hop >= self.depth or item.far_side:
                continue
            self.expanded.add(key)
            self.expand(item)
        self._states()

    def _states(self) -> None:
        """Only states an in-scope action actually reads or writes, never every state on the entity."""
        for action_id in [i for kind, i in self.included if kind == "node" and i in self.graph.actions]:
            action = self.graph.actions[action_id]
            for blob in (*action.preconditions, *action.effects):
                attr = str(blob.get("attribute_id") or "")
                rec = self.graph.fields.get(attr)
                if rec is None or ("node", rec.entity_id) not in self.included:
                    continue
                entity = self.graph.entities[rec.entity_id]
                values = blob.get("values")
                if values is None and blob.get("value") is not None and not isinstance(blob.get("value"), list):
                    values = [blob["value"]]
                elif isinstance(blob.get("value"), list):
                    values = blob["value"]
                for value in values or []:
                    if rec.name in STATE_FIELDS or str(value) in entity.states:
                        self.add(
                            "state",
                            f"{rec.entity_id}:{value}",
                            origin="expanded",
                            hop=self.depth,
                            expandable=False,
                            name=f"{rec.entity}.{rec.name}={value}",
                        )


def _seed(walk: _Walk, refs: RequirementRefs) -> None:
    graph = walk.graph
    for node_id, role in refs.nodes:
        if node_id in graph.actions:
            action = graph.actions[node_id]
            walk.seeds.add(node_id)
            walk.add("node", node_id, origin="seed", hop=0, expandable=True, name=action.name)
            if role == "result":
                walk.seeds.add(node_id)
        elif node_id in graph.entities:
            walk.add("node", node_id, origin="seed", hop=0, expandable=True, name=graph.entities[node_id].name)
    for field_id, _role in refs.fields:
        rec = graph.fields.get(field_id)
        if rec is None:
            continue
        walk.add("field", field_id, origin="seed", hop=0, expandable=True, name=rec.name)
        if rec.entity_id in graph.entities:
            walk.add("node", rec.entity_id, origin="seed", hop=0, expandable=True, name=rec.entity)
    for link_id, _role in refs.links:
        link = graph.links.get(link_id)
        if link is None:
            continue
        walk.add("link", link_id, origin="seed", hop=0, expandable=True, name=link.name())


def compute_included(graph: Graph, refs: RequirementRefs, depth: int) -> dict[tuple[str, str], Item]:
    prepare(graph)
    walk = _Walk(graph, depth)
    _seed(walk, refs)
    walk.run()
    return walk.included


def _public_item(item: Item, **extra) -> dict:
    out = {"id": item.id, "name": item.name, "origin": item.origin, **extra}
    if item.far_side:
        out["far_side"] = True
    if not item.cover:
        out["cover"] = False
    return out


def build_targets(graph: Graph, included: dict[tuple[str, str], Item]) -> list[dict]:
    targets: list[dict] = []
    fields = [included[k] for k in sorted(included) if k[0] == "field" and included[k].cover]
    for item in fields:
        rec = graph.fields.get(item.id)
        if rec is None:
            continue
        targets.append(
            {
                "id": f"field:{item.id}",
                "type": "field",
                "attribute_id": item.id,
                "entity_id": rec.entity_id,
                "entity": rec.entity,
                "name": rec.name,
            }
        )
    actions = [
        included[k]
        for k in sorted(included, key=lambda key: (included[key].name, key[1]))
        if k[0] == "node" and k[1] in graph.actions and included[k].cover
    ]
    link_names = {lk.id: lk.name() for lk in graph.links.values()}
    for item in actions:
        action = graph.actions[item.id]
        targets.append({"id": f"action:{action.id}", "type": "action", "action_id": action.id, "action": action.name})
        if action.preconditions:
            when = " ; ".join(precondition_text(p) for p in action.preconditions)
            targets.append(
                {
                    "id": f"pre_met:{action.id}",
                    "type": "precondition_met",
                    "action_id": action.id,
                    "action": action.name,
                    "when": when,
                }
            )
            for index, pre in enumerate(action.preconditions):
                targets.append(
                    {
                        "id": f"pre_bad:{action.id}:{index}",
                        "type": "precondition_violated",
                        "action_id": action.id,
                        "action": action.name,
                        "when": precondition_text(pre),
                    }
                )
        for index, effect in enumerate(action.effects):
            if (effect.get("kind") or "set_field") == "set_field" and effect.get("values"):
                for j, value in enumerate(effect["values"]):
                    targets.append(
                        {
                            "id": f"effect:{action.id}:{index}:{j}",
                            "type": "effect",
                            "action_id": action.id,
                            "action": action.name,
                            "then": f"{effect.get('field')} → {value}",
                        }
                    )
            else:
                targets.append(
                    {
                        "id": f"effect:{action.id}:{index}",
                        "type": "effect",
                        "action_id": action.id,
                        "action": action.name,
                        "then": effect_text(effect, link_names),
                    }
                )
    constraints = [included[k] for k in sorted(included) if k[0] == "constraint" and included[k].cover]
    for item in constraints:
        entity_id = item.id.split(":", 1)[0]
        entity = graph.entities.get(entity_id)
        targets.append(
            {
                "id": f"constraint:{item.id}",
                "type": "constraint",
                "entity_id": entity_id,
                "entity": entity.name if entity else "",
                "text": item.name,
            }
        )
    links = [included[k] for k in sorted(included) if k[0] == "link" and included[k].cover]
    for item in links:
        link = graph.links.get(item.id)
        if link is None:
            continue
        common = {
            "link_id": link.id,
            "name": link.name(),
            "cardinality": CARD_TEXT.get(link.cardinality, link.cardinality),
            "required": link.required,
            "endpoint_ids": list(link.ends()),
        }
        if link.fk_attribute_id:
            common["fk_attribute_id"] = link.fk_attribute_id
        missing = "必填外键缺失应当拒绝" if link.required else "链接可空：缺失不是必填校验"
        targets.append(
            {
                "id": f"link_missing:{link.id}",
                "type": "link_missing",
                "when": missing,
                "nullable": not link.required,
                **common,
            }
        )
        targets.append(
            {
                "id": f"link_dangling:{link.id}",
                "type": "link_dangling",
                "when": "指向不存在的对象",
                **common,
            }
        )
        boundary = CARD_BOUNDARY.get(link.cardinality)
        if boundary:
            targets.append({"id": f"link_card:{link.id}", "type": "link_cardinality", "when": boundary, **common})
    return targets


def manifest_from(
    graph: Graph,
    refs: RequirementRefs,
    depth: int,
    included: dict[tuple[str, str], Item],
    *,
    suppress: list[dict] | None = None,
    manual: list[dict] | None = None,
) -> dict:
    nodes, fields, links, apis, states = [], [], [], [], []
    for key in sorted(included, key=lambda k: (included[k].kind, included[k].name, k[1])):
        item = included[key]
        if item.kind == "node" and item.id in graph.actions:
            nodes.append(_public_item(item, kind="action"))
        elif item.kind == "node" and item.id in graph.entities:
            nodes.append(_public_item(item, kind="entity"))
        elif item.kind == "field":
            rec = graph.fields.get(item.id)
            fields.append(_public_item(item, entity=rec.entity if rec else "", entity_id=rec.entity_id if rec else ""))
        elif item.kind == "link":
            link = graph.links.get(item.id)
            links.append(
                _public_item(
                    item,
                    cardinality=CARD_TEXT.get(link.cardinality, link.cardinality) if link else "",
                    required=bool(link and link.required),
                )
            )
        elif item.kind == "api":
            api = graph.apis.get(item.id)
            if api is None:
                continue
            apis.append(
                {
                    "id": api.id,
                    "method": api.method,
                    "path": api.path,
                    "action_id": api.action_id,
                    "origin": item.origin,
                    **({"cover": False} if not item.cover else {}),
                }
            )
        elif item.kind == "state":
            states.append({"id": item.id, "name": item.name, "origin": item.origin})
    body = {
        "requirement": {"id": refs.id, "code": refs.code, "title": refs.title},
        "depth": depth,
        "nodes": nodes,
        "fields": fields,
        "links": links,
        "apis": apis,
        "states": states,
        "targets": build_targets(graph, included),
        "suppress": suppress or [],
        "manual": manual or [],
    }
    body["fingerprint"] = fingerprint(refs, depth, [t["id"] for t in body["targets"]])
    return body


def fingerprint(refs: RequirementRefs, depth: int, target_ids: list[str]) -> str:
    payload = {
        "nodes": sorted(f"{i}:{role}" for i, role in refs.nodes),
        "fields": sorted(f"{i}:{role}" for i, role in refs.fields),
        "links": sorted(f"{i}:{role}" for i, role in refs.links),
        "depth": depth,
        "targets": sorted(target_ids),
    }
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(raw.encode()).hexdigest()


def blocked_manifest(refs: RequirementRefs, depth: int) -> dict:
    return {
        "blocked": True,
        "requirement": {"id": refs.id, "code": refs.code, "title": refs.title},
        "depth": depth,
        "message": f"需求 {refs.code} {MISSING_REFS}",
        "nodes": [],
        "fields": [],
        "links": [],
        "apis": [],
        "states": [],
        "targets": [],
        "suppress": [],
        "manual": [],
    }


def compute_manifest(graph: Graph, refs: RequirementRefs, depth: int) -> dict:
    if depth not in (0, 1, 2):
        raise ValueError("depth must be 0, 1 or 2")
    if not refs.has_refs():
        return blocked_manifest(refs, depth)
    included = compute_included(graph, refs, depth)
    if not any(k[0] in ("node", "field", "link") for k in included):
        return blocked_manifest(refs, depth)
    return manifest_from(graph, refs, depth, included)


def refresh_states(graph: Graph, included: dict[tuple[str, str], Item]) -> None:
    """Recompute state rows from the actions that are still in the manifest."""
    prepare(graph)
    for key in [k for k in included if k[0] == "state"]:
        included.pop(key, None)
    walk = _Walk(graph, 0)
    walk.included = included
    walk._states()


def prompt_scope(manifest: dict) -> dict:
    """Short form for the prompt: ids, names, origins and coverage targets. No schemas."""
    if manifest.get("blocked"):
        return {
            "requirement": manifest["requirement"],
            "depth": manifest["depth"],
            "blocked": True,
            "message": manifest.get("message"),
        }
    keep_node = ("id", "kind", "name", "origin", "far_side")
    keep_field = ("id", "entity", "name", "origin", "far_side", "cover")
    keep_link = ("id", "name", "origin", "cardinality", "required", "far_side", "cover")
    keep_api = ("id", "method", "path", "origin")

    def pick(rows, keys):
        out = []
        for row in rows:
            item = {k: row[k] for k in keys if k in row and row[k] is not None}
            if row.get("far_side"):
                item["far_side"] = True
            if row.get("cover") is False:
                item["cover"] = False
            out.append(item)
        return out

    return {
        "requirement": {
            "code": manifest["requirement"]["code"],
            "title": manifest["requirement"]["title"],
            "id": manifest["requirement"]["id"],
        },
        "depth": manifest["depth"],
        "nodes": pick(manifest.get("nodes") or [], keep_node),
        "fields": pick(manifest.get("fields") or [], keep_field),
        "links": pick(manifest.get("links") or [], keep_link),
        "apis": pick(manifest.get("apis") or [], keep_api),
        "states": [{"id": s["id"], "name": s["name"]} for s in manifest.get("states") or []],
        "targets": manifest.get("targets") or [],
        "fingerprint": manifest.get("fingerprint"),
    }


def items_from_manifest(manifest: dict) -> dict[tuple[str, str], Item]:
    """Rebuild the walk items from a stored manifest so an edit does not recompute depth."""
    included: dict[tuple[str, str], Item] = {}
    for node in manifest.get("nodes") or []:
        included[("node", node["id"])] = Item(
            "node",
            node["id"],
            node.get("origin") or "expanded",
            0,
            False,
            bool(node.get("far_side")),
            node.get("cover", True),
            node.get("name") or "",
        )
    for row in manifest.get("fields") or []:
        included[("field", row["id"])] = Item(
            "field",
            row["id"],
            row.get("origin") or "expanded",
            0,
            False,
            bool(row.get("far_side")),
            row.get("cover", True),
            row.get("name") or "",
        )
    for row in manifest.get("links") or []:
        included[("link", row["id"])] = Item(
            "link",
            row["id"],
            row.get("origin") or "expanded",
            0,
            False,
            False,
            row.get("cover", True),
            row.get("name") or "",
        )
    for row in manifest.get("apis") or []:
        included[("api", row["id"])] = Item(
            "api",
            row["id"],
            row.get("origin") or "expanded",
            0,
            False,
            False,
            row.get("cover", True),
            f"{row.get('method')} {row.get('path')}",
        )
    for row in manifest.get("states") or []:
        included[("state", row["id"])] = Item(
            "state", row["id"], row.get("origin") or "expanded", 0, False, False, False, row.get("name") or ""
        )
    for target in manifest.get("targets") or []:
        if target["type"] != "constraint":
            continue
        suffix = target["id"].removeprefix("constraint:")
        included[("constraint", suffix)] = Item(
            "constraint", suffix, "expanded", 0, False, False, True, target.get("text") or ""
        )
    return included


def drop_item(graph: Graph, included: dict[tuple[str, str], Item], kind: str, id_: str) -> None:
    """Remove one preview row and the pieces that existed only because of it."""
    key = (kind if kind != "entity" and kind != "action" else "node", id_)
    if kind in ("entity", "action", "node"):
        key = ("node", id_)
    included.pop(key, None)
    if kind in ("entity", "node") and id_ in graph.entities:
        for fid in list(graph.fields_by_entity.get(id_, [])):
            included.pop(("field", fid), None)
        for cid in [k for k in included if k[0] == "constraint" and k[1].startswith(f"{id_}:")]:
            included.pop(cid, None)
        for sid in [k for k in included if k[0] == "state" and k[1].startswith(f"{id_}:")]:
            included.pop(sid, None)
        for link_id in list(graph.links_by_entity.get(id_, [])):
            included.pop(("link", link_id), None)
        _drop_orphan_far_sides(graph, included)
    if kind in ("action", "node") and id_ in graph.actions:
        for api in graph.actions[id_].api_ids:
            included.pop(("api", api), None)
    if kind == "link":
        included.pop(("link", id_), None)
        _drop_orphan_far_sides(graph, included)
    if kind == "field":
        included.pop(("field", id_), None)
    if kind == "api":
        included.pop(("api", id_), None)


def _drop_orphan_far_sides(graph: Graph, included: dict[tuple[str, str], Item]) -> None:
    live_links = [graph.links[i] for kind, i in included if kind == "link" and i in graph.links]
    touched = {end for link in live_links for end in link.ends()}
    for item in list(included.values()):
        if item.kind == "node" and item.far_side and item.id not in touched:
            drop_item(graph, included, "entity", item.id)


def add_manual(graph: Graph, included: dict[tuple[str, str], Item], kind: str, id_: str, *, cover: bool) -> None:
    prepare(graph)
    origin = "manual"
    if kind in ("entity", "node") and id_ in graph.entities:
        entity = graph.entities[id_]
        included[("node", id_)] = Item("node", id_, origin, 0, False, False, cover, entity.name)
        if cover:
            for fid in graph.fields_by_entity.get(id_, []):
                rec = graph.fields[fid]
                included[("field", fid)] = Item("field", fid, origin, 0, False, False, True, rec.name)
            for index, text in enumerate(entity.constraints):
                included[("constraint", f"{id_}:{index}")] = Item(
                    "constraint", f"{id_}:{index}", origin, 0, False, False, True, text
                )
        return
    if kind in ("action", "node") and id_ in graph.actions:
        action = graph.actions[id_]
        included[("node", id_)] = Item("node", id_, origin, 0, False, False, cover, action.name)
        if cover:
            for api_id in action.api_ids:
                api = graph.apis.get(api_id)
                if api:
                    included[("api", api_id)] = Item(
                        "api", api_id, origin, 0, False, False, True, f"{api.method} {api.path}"
                    )
        return
    if kind == "field" and id_ in graph.fields:
        rec = graph.fields[id_]
        included[("field", id_)] = Item("field", id_, origin, 0, False, False, cover, rec.name)
        if ("node", rec.entity_id) not in included and rec.entity_id in graph.entities:
            ent = graph.entities[rec.entity_id]
            included[("node", rec.entity_id)] = Item("node", rec.entity_id, origin, 0, False, False, cover, ent.name)
        return
    if kind == "link" and id_ in graph.links:
        link = graph.links[id_]
        included[("link", id_)] = Item("link", id_, origin, 0, False, False, cover, link.name())
        if cover:
            for end in link.ends():
                if ("node", end) not in included and end in graph.entities:
                    ent = graph.entities[end]
                    included[("node", end)] = Item("node", end, origin, 0, False, True, True, ent.name)
                    for fid in graph.fields_by_entity.get(end, []):
                        rec = graph.fields[fid]
                        included.setdefault(("field", fid), Item("field", fid, origin, 0, False, True, True, rec.name))
        return
    if kind == "api" and id_ in graph.apis:
        api = graph.apis[id_]
        included[("api", id_)] = Item("api", id_, origin, 0, False, False, cover, f"{api.method} {api.path}")
        return
    raise KeyError(id_)


def target_label(target: dict) -> str:
    if target.get("type") == "field":
        return f"{target.get('entity')}.{target.get('name')}"
    if target.get("type") == "action":
        return str(target.get("action") or target.get("id"))
    if target.get("text"):
        return str(target["text"])
    return str(target.get("when") or target.get("then") or target.get("name") or target["id"])


def _ids(case, key: str) -> set[str]:
    raw = case[key] if isinstance(case, dict) else getattr(case, key, None)
    return {str(item) for item in raw or []}


def case_covers_target(target: dict, case) -> bool:
    """A hit is structural: field ids, node ids, and an explicit covers entry. Titles do not count."""
    nodes = _ids(case, "node_ids")
    attrs = _ids(case, "attribute_ids")
    covers = _ids(case, "covers")
    kind = target.get("type")
    if kind == "field":
        return str(target.get("attribute_id")) in attrs
    if kind == "action":
        return str(target.get("action_id")) in nodes
    if kind in ("precondition_met", "precondition_violated", "effect"):
        return target["id"] in covers and str(target.get("action_id")) in nodes
    if kind == "constraint":
        return target["id"] in covers and str(target.get("entity_id")) in nodes
    if kind in ("link_missing", "link_dangling", "link_cardinality"):
        ends = {str(item) for item in target.get("endpoint_ids") or []}
        return target["id"] in covers and bool(nodes & ends)
    return False


def derive_chains(graph: Graph) -> list[dict]:
    """Maximal paths where one action's effect satisfies the next action's precondition.

    Read-only actions are not steps. This is not a deeper single-requirement scope.
    """
    prepare(graph)
    edges: dict[str, list[tuple[str, str]]] = {}
    indegree: dict[str, int] = {}
    for source in graph.actions.values():
        if source.read_only:
            continue
        for other in graph.actions.values():
            if other.id == source.id or other.read_only:
                continue
            reason = ""
            for effect in source.effects:
                if any(effect_enables(effect, pre) for pre in other.preconditions):
                    reason = effect_text(effect)
                    break
            if not reason:
                continue
            edges.setdefault(source.id, []).append((other.id, reason))
            indegree[other.id] = indegree.get(other.id, 0) + 1
            indegree.setdefault(source.id, indegree.get(source.id, 0))
    linked = set(edges) | {to for pairs in edges.values() for to, _ in pairs}
    sources = sorted((i for i in linked if indegree.get(i, 0) == 0), key=lambda i: graph.actions[i].name)
    found: list[dict] = []

    def walk(path: list[str], transitions: list[dict]) -> None:
        nxt = [(to, why) for to, why in edges.get(path[-1], []) if to not in path]
        if not nxt:
            if len(path) >= 2:
                found.append(
                    {
                        "actions": [{"id": i, "name": graph.actions[i].name} for i in path],
                        "transitions": transitions,
                    }
                )
            return
        for to, why in sorted(nxt, key=lambda item: graph.actions[item[0]].name):
            step = {
                "id": f"transition:{path[-1]}:{to}",
                "from_id": path[-1],
                "to_id": to,
                "from": graph.actions[path[-1]].name,
                "to": graph.actions[to].name,
                "when": why,
            }
            walk([*path, to], [*transitions, step])

    for source in sources:
        walk([source], [])
    return found


def names_of(manifest: dict, kind: str) -> set[str]:
    if kind == "node":
        return {n["name"] for n in manifest.get("nodes") or []}
    if kind == "field":
        return {f"{f.get('entity')}.{f['name']}" for f in manifest.get("fields") or []}
    if kind == "link":
        return {lk["name"] for lk in manifest.get("links") or []}
    if kind == "action":
        return {n["name"] for n in manifest.get("nodes") or [] if n.get("kind") == "action"}
    return set()
