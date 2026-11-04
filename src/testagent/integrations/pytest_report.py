"""Readable run report for pytest executions: a pytest plugin loaded by the platform's
pytest executor (``-p testagent.integrations.pytest_report``) that records, per test:

- steps: named by the repo's ``step()`` helper, else by ``# Step N: …`` / ``# Setup: …``
  comments in the test source (existing scripts), else one step;
- inside each step, Playwright API requests (method, URL, status, request/response bodies,
  truncated), page actions (goto/click/fill/…), plain ``assert`` statements (passed and failed,
  via pytest's assertion pass hook) and ``check()`` / ``expect()`` results with expected vs
  actual;
- the test data keys the script reads, the duration, and the error explained in plain language.

The report is written as JSON to ``$TESTAGENT_REPORT``; without that variable the plugin is
inert, so running the repo's tests by hand is unaffected."""

from __future__ import annotations

import ast
import contextlib
import functools
import json
import os
import re
import sys
import time
from pathlib import Path

BODY_LIMIT = 2000
EVENT_LIMIT = 400
REPORT_ENV = "TESTAGENT_REPORT"
STEP_COMMENT = re.compile(
    r"^\s*#\s*((?:Setup|Preconditions?|Prepare|Cleanup|Teardown|Check|Verify "
    r"|Step\s*\d+(?:\s*check)?)\s*[:.]?\s*(.*))$",
    re.IGNORECASE,
)
DATA_KEY = re.compile(r"""(?:test_data|data)\s*(?:\[\s*|\.get\(\s*)["']([^"']+)["']""")
COMPARE = re.compile(r"^(.*?)\s+(==|!=|>=|<=|>|<|is not|is|not in|in)\s+(.*)$", re.S)
OP_TEXT = {
    "==": "equals",
    "!=": "does not equal",
    ">=": "is at least",
    "<=": "is at most",
    ">": "is greater than",
    "<": "is less than",
    "is": "is",
    "is not": "is not",
    "in": "is in",
    "not in": "is not in",
}

_state: dict = {"test": None}


def _short(value, limit: int = BODY_LIMIT):
    if value is None:
        return None
    if isinstance(value, (bytes, bytearray)):
        try:
            value = value.decode("utf-8")
        except UnicodeDecodeError:
            return f"<{len(value)} bytes of binary content>"
    if not isinstance(value, str):
        try:
            value = json.dumps(value, ensure_ascii=False, default=str)
        except (TypeError, ValueError):
            value = repr(value)
    return value if len(value) <= limit else value[:limit] + f"… ({len(value)} chars in total)"


def _repr(value, limit: int = 300) -> str:
    text = value if isinstance(value, str) and not value else repr(value)
    return text if len(text) <= limit else text[:limit] + "…"


# ------------------------------------------------------------------ recording
class _Test:
    def __init__(self, item):
        self.item = item
        self.file = str(Path(str(item.path)).resolve())
        self.func = getattr(item, "originalname", None) or item.name.split("[")[0]
        self.started = time.monotonic()
        self.events: list[dict] = []
        self.explicit: list[dict] = []  # steps from step(): {name, start, end, status}
        self.open: list[dict] = []
        self.dropped = 0

    def line(self) -> int | None:
        """Line in the test file of the call being recorded (outermost frame inside the test
        function, else any frame in the test file)."""
        fallback = None
        frame = sys._getframe(2)
        while frame is not None:
            name = frame.f_code.co_filename
            try:
                same = name == self.file or str(Path(name).resolve()) == self.file
            except OSError:
                same = False
            if same:
                if frame.f_code.co_name == self.func:
                    return frame.f_lineno
                fallback = fallback or frame.f_lineno
            frame = frame.f_back
        return fallback

    def add(self, event: dict) -> dict:
        if len(self.events) >= EVENT_LIMIT:
            self.dropped += 1
            return event
        event.setdefault("line", self.line())
        event["seq"] = len(self.events) + 1
        event["step"] = self.open[-1]["index"] if self.open else None
        self.events.append(event)
        return event


def current() -> _Test | None:
    return _state["test"]


@contextlib.contextmanager
def step(name: str):
    """Named step (used by the test repo's ``step`` fixture)."""
    test = current()
    if test is None:
        yield
        return
    entry = {"index": len(test.explicit), "name": str(name)[:200], "status": "passed"}
    entry["start"] = len(test.events)
    test.explicit.append(entry)
    test.open.append(entry)
    started = time.monotonic()
    try:
        yield
    except BaseException:
        entry["status"] = "failed"
        raise
    finally:
        entry["ms"] = int((time.monotonic() - started) * 1000)
        test.open.pop()


def check(name: str, actual, expected, op: str, passed: bool) -> None:
    """A named assertion (used by the test repo's ``check`` fixture)."""
    test = current()
    if test is None:
        return
    test.add(
        {
            "type": "check",
            "name": str(name)[:300],
            "op": op,
            "expected": _repr(expected),
            "actual": _repr(actual),
            "passed": bool(passed),
            "explain": None if passed else _explain_compare(name, _repr(actual), op, expected),
        }
    )


def _explain_compare(name: str, actual: str, op: str, expected) -> str:
    return f"{name}: expected {OP_TEXT.get(op, op)} {_repr(expected)}, got {actual}"


# ------------------------------------------------------------------ playwright wrappers
def _wrap_request(cls, method: str) -> None:
    original = getattr(cls, method, None)
    if original is None or getattr(original, "_ta_wrapped", False):
        return

    @functools.wraps(original)
    def wrapper(self, url, *args, **kwargs):
        test = current()
        if test is None:
            return original(self, url, *args, **kwargs)
        verb = (kwargs.get("method") or "GET").upper() if method == "fetch" else method.upper()
        body = next(
            (kwargs[k] for k in ("data", "json", "form", "multipart") if kwargs.get(k) is not None),
            None,
        )
        event = {"type": "request", "method": verb, "url": str(url), "request": _short(body)}
        if kwargs.get("params"):
            event["params"] = _short(kwargs["params"], 500)
        started = time.monotonic()
        try:
            response = original(self, url, *args, **kwargs)
        except Exception as exc:
            event.update(ms=int((time.monotonic() - started) * 1000), error=_short(str(exc), 500))
            test.add(event)
            raise
        event["ms"] = int((time.monotonic() - started) * 1000)
        try:
            event["url"] = response.url
            event["status"] = response.status
            event["response"] = _short(response.text())
        except Exception:  # noqa: BLE001 - binary or disposed bodies are fine to skip
            pass
        test.add(event)
        return response

    wrapper._ta_wrapped = True
    setattr(cls, method, wrapper)


def _target(obj, args) -> str | None:
    impl = getattr(obj, "_impl_obj", None)
    selector = getattr(impl, "_selector", None)
    if selector:
        return str(selector)[:300]
    return str(args[0])[:300] if args else None


def _wrap_action(cls, method: str, label: str, value_arg: int | None) -> None:
    original = getattr(cls, method, None)
    if original is None or getattr(original, "_ta_wrapped", False):
        return

    @functools.wraps(original)
    def wrapper(self, *args, **kwargs):
        test = current()
        if test is None:
            return original(self, *args, **kwargs)
        is_page = cls.__name__ == "Page"
        target = _target(self, args) if not is_page or method != "goto" else None
        if is_page:
            target = str(args[0])[:300] if args else kwargs.get("url") or kwargs.get("selector")
        index = (value_arg + (1 if is_page and method != "goto" else 0)) if value_arg is not None else None
        value = args[index] if index is not None and len(args) > index else kwargs.get("value")
        event = {"type": "action", "action": label, "target": target}
        if value is not None:
            event["value"] = _short(value, 300)
        started = time.monotonic()
        try:
            result = original(self, *args, **kwargs)
        except Exception as exc:
            event.update(ms=int((time.monotonic() - started) * 1000), ok=False, error=_short(str(exc), 600))
            test.add(event)
            raise
        event.update(ms=int((time.monotonic() - started) * 1000), ok=True)
        if method == "goto" and result is not None:
            with contextlib.suppress(Exception):
                event["status"] = result.status
        test.add(event)
        return result

    wrapper._ta_wrapped = True
    setattr(cls, method, wrapper)


def _wrap_expect(cls) -> None:
    for name in dir(cls):
        if not name.startswith(("to_", "not_to_")):
            continue
        original = getattr(cls, name)
        if getattr(original, "_ta_wrapped", False) or not callable(original):
            continue

        def make(original, name):
            @functools.wraps(original)
            def wrapper(self, *args, **kwargs):
                test = current()
                if test is None:
                    return original(self, *args, **kwargs)
                impl = getattr(self, "_impl_obj", None)
                actual = getattr(impl, "_actual_locator", None) or getattr(impl, "_actual_page", None)
                subject = getattr(actual, "_selector", None) or getattr(actual, "url", None)
                expected = args[0] if args else (next(iter(kwargs.values())) if kwargs else None)
                event = {
                    "type": "check",
                    "name": f"expect({subject or 'Page'}).{name}",
                    "op": name,
                    "expected": _repr(expected) if expected is not None else None,
                }
                try:
                    result = original(self, *args, **kwargs)
                except AssertionError as exc:
                    event.update(passed=False, actual=None, explain=_short(str(exc), 800))
                    exc._ta_recorded = True
                    test.add(event)
                    raise
                event["passed"] = True
                test.add(event)
                return result

            wrapper._ta_wrapped = True
            return wrapper

        setattr(cls, name, make(original, name))


ACTIONS = {
    "goto": ("Open", None),
    "click": ("Click", None),
    "dblclick": ("Double-click", None),
    "fill": ("Fill", 0),
    "type": ("Type", 0),
    "press": ("Press", 0),
    "select_option": ("Select", 0),
    "check": ("Check", None),
    "uncheck": ("Uncheck", None),
    "set_input_files": ("Upload file", 0),
}


def _patch_playwright() -> None:
    try:
        from playwright import sync_api
    except ImportError:  # the repo may not use Playwright at all
        return
    for method in ("get", "post", "put", "patch", "delete", "head", "fetch"):
        _wrap_request(sync_api.APIRequestContext, method)
    for method, (label, value_arg) in ACTIONS.items():
        if method != "goto":
            _wrap_action(sync_api.Locator, method, label, value_arg)
        _wrap_action(sync_api.Page, method, label, value_arg)
    for name in ("PageAssertions", "LocatorAssertions", "APIResponseAssertions"):
        cls = getattr(sync_api, name, None)
        if cls is not None:
            _wrap_expect(cls)


# ------------------------------------------------------------------ assertions & errors
def _split_compare(source: str) -> tuple[str, str, str] | None:
    try:
        node = ast.parse(source.strip(), mode="eval").body
    except SyntaxError:
        return None
    if isinstance(node, ast.Compare) and len(node.ops) == 1:
        ops = {
            ast.Eq: "==",
            ast.NotEq: "!=",
            ast.GtE: ">=",
            ast.LtE: "<=",
            ast.Gt: ">",
            ast.Lt: "<",
            ast.Is: "is",
            ast.IsNot: "is not",
            ast.In: "in",
            ast.NotIn: "not in",
        }
        op = ops.get(type(node.ops[0]))
        if op:
            return ast.unparse(node.left), op, ast.unparse(node.comparators[0])
    return None


def _values(expl: str) -> tuple[str, str] | None:
    first = (expl or "").strip().splitlines()[0] if (expl or "").strip() else ""
    first = first.removeprefix("assert ").strip()
    match = COMPARE.match(first)
    return (match.group(1), match.group(3)) if match else None


def assertion_event(source: str, expl: str, passed: bool, message: str | None = None) -> dict:
    """{'type': 'check', 'name': <assert source>, expected/actual …} for a plain assert."""
    source = " ".join((source or "").split())
    event = {"type": "check", "name": source[:300], "passed": passed, "assert": True}
    parts = _split_compare(source)
    values = _values(expl)
    if parts:
        left, op, right = parts
        event["op"] = op
        event["subject"] = left[:200]
        event["expected"] = right[:300]
        if values:
            event["actual"] = values[0][:300]
            if values[1] != right:
                event["expected"] = f"{right} (= {values[1][:200]})"
    elif values:
        event["actual"] = f"{values[0]} … {values[1]}"[:300]
    if not passed:
        event["explain"] = explain_assert(event, message)
    return event


def explain_assert(event: dict, message: str | None) -> str:
    subject, op = event.get("subject"), event.get("op")
    actual = event.get("actual")
    if subject and op and actual is not None:
        if re.search(r"\.status(_code)?$", subject):
            text = f"API returned status code {actual}, expected {OP_TEXT.get(op, op)} {event['expected']}"
        else:
            text = f"expected {subject} {OP_TEXT.get(op, op)} {event['expected']}, got {actual}"
    else:
        text = f"Assertion failed: {event['name']}"
    if message:
        text += f" (script note: {message[:300]})"
    return text


def error_kind(exc_type: str, message: str) -> str:
    """Failure kind of a non-assertion error (batch 2): env_unreachable, locator, timeout,
    http_error or script_error. Mirrors the branches of ``explain_error``."""
    text = message or exc_type
    if "ECONNREFUSED" in text or "Connection refused" in text or "connect ECONN" in text:
        return "env_unreachable"
    if exc_type == "TimeoutError" or "Timeout" in exc_type or "Timeout " in text:
        return "locator" if re.search(r"locator|waiting for", text) else "timeout"
    if exc_type in ("JSONDecodeError", "ValueError") and "JSON" in text.upper():
        return "http_error"
    return "script_error"


def failure_detail(event: dict, test) -> dict:
    """Structured expected / actual of a failed check or assert event (readable summary)."""
    out = {"kind": "assertion"}
    for key in ("subject", "expected", "actual"):
        if event.get(key) is not None:
            out[key] = event[key]
    if event.get("type") == "check" and event.get("name"):
        out["check"] = event["name"]
    index = event.get("step")
    if index is not None and test is not None and index < len(test.explicit):
        out["step"] = test.explicit[index]["name"]
    return out


def explain_error(exc_type: str, message: str) -> str:
    text = message or exc_type
    if "ECONNREFUSED" in text or "Connection refused" in text or "connect ECONN" in text:
        return "Cannot connect to the SUT: make sure the environment is running and the address is correct"
    if exc_type == "TimeoutError" or "Timeout" in exc_type or "Timeout " in text:
        found = re.search(r'(?:locator|waiting for)\s*\(?["\']?([^"\'\n)]+)', text)
        where = f": {found.group(1)[:120]}" if found else ""
        return f"Page action timed out: the element did not appear or become actionable in time{where}"
    if exc_type == "KeyError":
        return f"Data has no field {text} (the response or test data lacks this field)"
    if exc_type in ("JSONDecodeError", "ValueError") and "JSON" in text.upper():
        return "The response is not valid JSON (an error page may have been returned)"
    if exc_type == "TypeError" and "NoneType" in text:
        return f"Got an empty value (None) and kept using it: {text[:200]}"
    return f"Script error ({exc_type}): {text[:300]}"


# ------------------------------------------------------------------ step grouping
def _source_steps(item) -> tuple[list[tuple[int, str]], tuple[int, int] | None, str | None]:
    """[(line, name)] from step comments inside the test function, its line range, source."""
    path = Path(str(item.path))
    try:
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source)
    except (OSError, SyntaxError, UnicodeDecodeError):
        return [], None, None
    name = getattr(item, "originalname", None) or item.name.split("[")[0]
    func = next(
        (n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == name),
        None,
    )
    if func is None:
        return [], None, source
    lines = source.splitlines()
    span = (func.lineno, func.end_lineno or len(lines))
    steps = []
    for no in range(span[0], span[1] + 1):
        match = STEP_COMMENT.match(lines[no - 1])
        if match:
            steps.append((no, match.group(1).strip()))
    return steps, span, ast.get_source_segment(source, func)


def group_steps(test: _Test, comments: list[tuple[int, str]], span) -> list[dict]:
    events = test.events
    if test.explicit:
        steps: list[dict] = []
        by_index = {s["index"]: s for s in test.explicit}
        loose: dict | None = None
        for s in test.explicit:
            s["events"] = []
        order: list[dict] = []
        for ev in events:
            if ev["step"] is not None:
                target = by_index[ev["step"]]
                if target not in order:
                    order.append(target)
                target["events"].append(ev)
                loose = None
            else:
                if loose is None:
                    loose = {"name": "Other actions (unnamed step)", "events": [], "implicit": True}
                    order.append(loose)
                loose["events"].append(ev)
        for s in test.explicit:  # steps without any event still show up, in order
            if s not in order:
                order.append(s)
        order.sort(key=lambda s: s.get("start", s["events"][0]["seq"] if s["events"] else 0))
        for s in order:
            steps.append(
                {
                    "name": s["name"],
                    "status": s.get("status", "passed"),
                    "ms": s.get("ms"),
                    "events": s["events"],
                    "source": "implicit" if s.get("implicit") else "step",
                }
            )
        return steps
    if comments:
        steps = [{"name": "Setup", "line": None, "events": [], "source": "comment"}]
        steps += [{"name": n, "line": no, "events": [], "source": "comment"} for no, n in comments]
        current = 0
        for ev in events:
            line = ev.get("line")
            if line is not None and span and span[0] <= line <= span[1]:
                current = 0
                for i, (no, _) in enumerate(comments, start=1):
                    if no <= line:
                        current = i
            steps[current]["events"].append(ev)
        return [s for s in steps if s["events"] or s["line"] is not None]
    return [{"name": "Test steps", "events": events, "source": "single"}] if events else []


def _finish_steps(steps: list[dict], outcome: str) -> None:
    for s in steps:
        bad = [
            e
            for e in s["events"]
            if (e["type"] == "check" and e.get("passed") is False) or e.get("ok") is False or e.get("error")
        ]
        if bad:
            s["status"] = "failed"
        else:
            s.setdefault("status", "passed")
        s["checks"] = sum(1 for e in s["events"] if e["type"] == "check")
    if outcome in ("failed", "error") and steps and all(s["status"] == "passed" for s in steps):
        steps[-1]["status"] = "failed"


# ------------------------------------------------------------------ pytest hooks
_tests: list[dict] = []


def _enabled() -> bool:
    return bool(os.environ.get(REPORT_ENV))


def pytest_configure(config):
    if _enabled():
        _patch_playwright()


def pytest_runtest_setup(item):
    if _enabled():
        _state["test"] = _Test(item)


def pytest_assertion_pass(item, lineno, orig, expl):
    test = current()
    if test is not None:
        event = assertion_event(orig, expl, True)
        event["line"] = lineno
        test.add(event)


def _assert_source(path: str, line: int | None) -> tuple[str, str | None]:
    """Source of the assert statement covering ``line`` (multi-line asserts too) and its
    message expression."""
    if not line:
        return "", None
    try:
        tree = ast.parse(Path(path).read_text(encoding="utf-8"))
    except (OSError, SyntaxError, UnicodeDecodeError):
        return "", None
    for node in ast.walk(tree):
        if isinstance(node, ast.Assert) and node.lineno <= line <= (node.end_lineno or line):
            message = None
            if isinstance(node.msg, ast.Constant) and isinstance(node.msg.value, str):
                message = node.msg.value
            return ast.unparse(node.test), message
    return "", None


def pytest_runtest_makereport(item, call):
    test = current()
    if test is None or call.when != "call" or call.excinfo is None:
        return
    exc = call.excinfo.value
    if getattr(exc, "_ta_recorded", False):
        # check() / expect() already recorded the failed event; keep it as the test's failure
        failed = next((e for e in reversed(test.events) if e.get("passed") is False), None)
        if failed is not None and getattr(test, "failure", None) is None:
            test.failure = {
                "type": "AssertionError",
                "message": _short(str(exc), 1500),
                "explain": failed.get("explain") or _short(str(exc), 800),
                **failure_detail(failed, test),
            }
        return
    line = None
    for entry in reversed(call.excinfo.traceback):
        if str(Path(str(entry.path)).resolve()) == test.file:
            line = entry.lineno + 1
            break
    if isinstance(exc, AssertionError):
        source, message = _assert_source(test.file, line)
        text = str(exc)
        if "\nassert " in text:
            head, _, rest = text.partition("\nassert ")
            expl = "assert " + rest
            message = message or head
        else:
            expl = text
        source = source or expl
        event = assertion_event(source, expl, False, message)
        event["line"] = line
        test.add(event)
        test.failure = {"type": "AssertionError", "message": _short(text, 1500)}
        test.failure["explain"] = event["explain"]
        test.failure.update(failure_detail(event, test))
    else:
        name = type(exc).__name__
        test.add({"type": "error", "name": name, "message": _short(str(exc), 1500), "line": line})
        test.failure = {
            "type": name,
            "message": _short(str(exc), 1500),
            "explain": explain_error(name, str(exc)),
            "kind": error_kind(name, str(exc)),
        }


def pytest_runtest_logreport(report):
    test = current()
    if test is None or report.when != "teardown":
        return
    _state["test"] = None


def pytest_runtest_teardown(item, nextitem):
    test = current()
    if test is None:
        return
    outcome = "passed"
    failure = getattr(test, "failure", None)
    if failure:
        outcome = "failed" if failure["type"] == "AssertionError" else "error"
    comments, span, source = _source_steps(item)
    steps = group_steps(test, comments, span)
    _finish_steps(steps, outcome)
    used = sorted(set(DATA_KEY.findall(source or "")))
    _tests.append(
        {
            "name": item.nodeid,
            "title": (item.function.__doc__ or "").strip().splitlines()[0]
            if getattr(item, "function", None) is not None and item.function.__doc__
            else None,
            "outcome": outcome,
            "duration_ms": int((time.monotonic() - test.started) * 1000),
            "steps": steps,
            "checks": {
                "total": sum(1 for e in test.events if e["type"] == "check"),
                "failed": sum(1 for e in test.events if e["type"] == "check" and e.get("passed") is False),
            },
            "requests": sum(1 for e in test.events if e["type"] == "request"),
            "data_keys": used,
            "failure": failure,
            "dropped_events": test.dropped,
        }
    )


def pytest_sessionfinish(session, exitstatus):
    target = os.environ.get(REPORT_ENV)
    if not target:
        return
    payload = {"version": 1, "tests": _tests}
    Path(target).write_text(json.dumps(payload, ensure_ascii=False, default=str), encoding="utf-8")
