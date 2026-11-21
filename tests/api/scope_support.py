"""Confirm a scope snapshot and make scripted cases hit its coverage targets."""

V1 = "/api/v1"


def ready_scope(client, version_id, requirement_ids=None):
    body = {} if requirement_ids is None else {"requirement_ids": list(requirement_ids)}
    resp = client.post(f"{V1}/versions/{version_id}/case-gen/scope", json=body)
    assert resp.status_code == 200, resp.text
    scopes = resp.json()["scopes"]
    live = [s["requirement_id"] for s in scopes if s.get("id")]
    if live:
        confirmed = client.post(
            f"{V1}/versions/{version_id}/case-gen/scope/confirm",
            json={"requirement_ids": live},
        )
        assert confirmed.status_code == 200, confirmed.text
    return scopes


def _hit(target: dict, case: dict) -> bool:
    nodes = set(case.get("node_ids") or [])
    attrs = set(case.get("attribute_ids") or [])
    covers = set(case.get("covers") or [])
    kind = target["type"]
    if kind == "field":
        return target.get("attribute_id") in attrs
    if kind == "action":
        return target.get("action_id") in nodes
    if kind in ("precondition_met", "precondition_violated", "effect"):
        return target["id"] in covers and target.get("action_id") in nodes
    if kind == "constraint":
        return target["id"] in covers and target.get("entity_id") in nodes
    if kind in ("link_missing", "link_dangling", "link_cardinality"):
        return target["id"] in covers and bool(set(target.get("endpoint_ids") or []) & nodes)
    return False


def _add(case: dict, target: dict) -> None:
    nodes = list(case.get("node_ids") or [])
    attrs = list(case.get("attribute_ids") or [])
    covers = list(case.get("covers") or [])
    if target["id"] not in covers:
        covers.append(target["id"])
    for key, bucket in (("attribute_id", attrs), ("action_id", nodes), ("entity_id", nodes)):
        value = target.get(key)
        if value and value not in bucket:
            bucket.append(value)
    for end in target.get("endpoint_ids") or []:
        if end not in nodes:
            nodes.append(end)
    case["node_ids"] = nodes
    case["attribute_ids"] = attrs
    case["covers"] = covers


def stamp_cases(cases: list[dict], scopes: list[dict]) -> list[dict]:
    """Give the first case of each requirement whatever is still missing, without moving ids that are already there."""
    by_code = {}
    for scope in scopes:
        manifest = scope.get("manifest") or {}
        code = (manifest.get("requirement") or {}).get("code")
        if code and not manifest.get("blocked"):
            by_code[code] = manifest
    for code, manifest in by_code.items():
        mine = [c for c in cases if code in (c.get("requirement_codes") or [])]
        if not mine:
            continue
        for target in manifest.get("targets") or []:
            if any(_hit(target, c) for c in mine):
                continue
            _add(mine[0], target)
    return cases
