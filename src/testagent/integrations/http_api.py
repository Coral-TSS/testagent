"""HTTP tools for the agent_api executor: API-type manual cases are executed with
plain HTTP requests instead of driving a browser.

Like the browser executor, every call is a structured step and only ``api_assert`` receipts
decide pass/fail; a transport error is an execution error; no assertion is NO_ASSERTION."""

from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Literal

from pydantic import BaseModel, Field

from testagent.integrations.browser import Verdict

Method = Literal["GET", "POST", "PUT", "PATCH", "DELETE"]
ApiAssertKind = Literal["status", "json_equals", "json_contains", "body_contains", "header"]
MAX_BODY = 4000


def json_path(value: Any, path: str | None) -> Any:
    """Dotted path into a JSON document: ``items.0.amount_minor``; empty = whole document."""
    if not path:
        return value
    for part in re.split(r"\.", path.strip(".")):
        if isinstance(value, list) and part.lstrip("-").isdigit():
            value = value[int(part)]
        elif isinstance(value, dict) and part in value:
            value = value[part]
        else:
            raise KeyError(path)
    return value


def _same(actual: Any, expected: Any) -> bool:
    if actual == expected:
        return True
    if isinstance(expected, str) and not isinstance(actual, str):
        try:
            return actual == json.loads(expected)
        except ValueError:
            return str(actual) == expected
    return False


class HttpApiSession:
    """One session per case; keeps the last response and named values for later steps."""

    def __init__(self, base_url: str, *, timeout_s: float = 15.0):
        self.base_url = base_url.rstrip("/")
        self.timeout_s = timeout_s
        self.steps: list[dict] = []
        self.receipts: list[dict] = []
        self.last: dict | None = None

    def _step(self, action: str, target: str | None, value, fn) -> dict:
        started = time.monotonic()
        step = {"seq": len(self.steps) + 1, "action": action, "target": target, "value": value}
        try:
            step["result"] = fn()
            step["status"] = "ok"
        except Exception as exc:  # recorded as an error step, the verdict becomes error
            step["result"] = str(exc).strip()[:300] or type(exc).__name__
            step["status"] = "error"
        step["ms"] = int((time.monotonic() - started) * 1000)
        self.steps.append(step)
        return step

    def request(
        self,
        method: str,
        path: str,
        body: Any = None,
        query: dict | None = None,
        headers: dict | None = None,
    ) -> dict:
        url = self.base_url + "/" + path.lstrip("/")
        if query:
            url += ("&" if "?" in url else "?") + urllib.parse.urlencode(query)

        def send() -> dict:
            data = None
            hdrs = {"Accept": "application/json", **(headers or {})}
            if body is not None:
                data = json.dumps(body, ensure_ascii=False).encode("utf-8")
                hdrs["Content-Type"] = "application/json"
            req = urllib.request.Request(url, data=data, method=method.upper(), headers=hdrs)
            try:
                with urllib.request.urlopen(req, timeout=self.timeout_s) as resp:  # noqa: S310
                    status, raw, rh = resp.status, resp.read(), dict(resp.headers)
            except urllib.error.HTTPError as exc:  # 4xx/5xx are results, not errors
                status, raw, rh = exc.code, exc.read(), dict(exc.headers or {})
            text = raw.decode("utf-8", errors="replace")
            try:
                parsed: Any = json.loads(text) if text else None
            except ValueError:
                parsed = None
            self.last = {"status": status, "text": text, "json": parsed, "headers": rh}
            shown = parsed if parsed is not None else text[:MAX_BODY]
            if len(json.dumps(shown, ensure_ascii=False, default=str)) > MAX_BODY:
                shown = text[:MAX_BODY] + "…"
            return {"status": status, "body": shown}

        return self._step("request", f"{method.upper()} {path}", body, send)

    def assert_(self, kind: str, expected: Any = None, path: str | None = None) -> dict:
        def evaluate() -> dict:
            if self.last is None:
                raise ValueError("no response yet: call api_request first")
            actual: Any
            if kind == "status":
                actual = self.last["status"]
                passed = str(actual) == str(expected)
            elif kind == "body_contains":
                actual = self.last["text"][:MAX_BODY]
                passed = expected is not None and str(expected) in self.last["text"]
            elif kind == "header":
                key = (path or "").lower()
                actual = next((v for k, v in self.last["headers"].items() if k.lower() == key), None)
                passed = actual is not None and (expected is None or str(expected) in actual)
            else:
                try:
                    actual = json_path(self.last["json"], path)
                except (KeyError, IndexError, TypeError):
                    actual, passed = None, False
                else:
                    if kind == "json_equals":
                        passed = _same(actual, expected)
                    else:  # json_contains
                        passed = expected is not None and str(expected) in json.dumps(
                            actual, ensure_ascii=False, default=str
                        )
            receipt = {
                "kind": kind,
                "target": path,
                "expected": expected,
                "actual": actual,
                "passed": passed,
            }
            self.receipts.append({**receipt, "seq": len(self.steps) + 1})
            return receipt

        step = self._step("assert", path, expected, evaluate)
        if step["status"] == "ok":
            step["assertion"] = "passed" if step["result"]["passed"] else "failed"
        return step

    def verdict(self) -> Verdict:
        errors = [s for s in self.steps if s["status"] == "error"]
        if errors:
            first = errors[0]
            return Verdict(status="error", error=f"step {first['seq']} {first['action']}: {first['result']}")
        if not self.receipts:
            return Verdict(status="error", error="NO_ASSERTION: the agent made no api_assert")
        failed = [r for r in self.receipts if not r["passed"]]
        if failed:
            r = failed[0]
            where = f" {r['target']}" if r["target"] else ""
            text = f"assert {r['kind']}{where}: expected {r['expected']!r}, actual {r['actual']!r}"
            return Verdict(status="failed", failed_assertion=text)
        return Verdict(status="passed")


class RequestArgs(BaseModel):
    method: Method
    path: str = Field(description="path relative to the environment base URL, e.g. /sample/orders")
    body: Any = Field(default=None, description="JSON request body, exactly per get_api_schema")
    query: dict[str, Any] | None = None
    headers: dict[str, str] | None = None


class ApiAssertArgs(BaseModel):
    kind: ApiAssertKind = Field(description="status (HTTP code) | json_equals | json_contains | body_contains | header")
    expected: Any = None
    path: str | None = Field(
        default=None,
        description="dotted JSON path of the last response for json_*, e.g. status or "
        "items.0.amount_minor; header name for header",
    )


API_TOOLS = ("api_request", "api_assert", "get_api_schema", "list_apis")


def register_api_tools(registry) -> None:
    from testagent.agent.tools import ToolSpec, to_text

    def session(ctx: dict) -> HttpApiSession:
        http = ctx.get("resources", {}).get("http")
        if http is None:
            raise ValueError("no HTTP session for this run")
        return http

    def reply(step: dict) -> str:
        return ("Error: " if step["status"] == "error" else "") + to_text(step)

    registry.register(
        ToolSpec(
            "api_request",
            "http",
            "Send one HTTP request to the system under test and return status + body.",
            RequestArgs,
            lambda ctx, method, path, body=None, query=None, headers=None: reply(
                session(ctx).request(method, path, body, query, headers)
            ),
            writes=True,
            needs_ctx=True,
        )
    )
    registry.register(
        ToolSpec(
            "api_assert",
            "http",
            "Check an expected result against the last response. Only these receipts decide "
            "pass/fail; call it for every expected result of the case.",
            ApiAssertArgs,
            lambda ctx, kind, expected=None, path=None: reply(session(ctx).assert_(kind, expected, path)),
            writes=True,
            needs_ctx=True,
        )
    )
