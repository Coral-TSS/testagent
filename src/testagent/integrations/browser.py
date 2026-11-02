"""Playwright browser tools for the agent_browser executor (architecture §5.2).

Every tool call becomes a structured step ``{seq, action, target, value, result, status,
screenshot_sha, ms}``. Only ``browser_assert`` receipts decide pass/fail; a tool error or timeout
makes the execution an error; no assertion at all is an error (NO_ASSERTION)."""

from __future__ import annotations

import os
import re
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

from testagent.core.artifacts import ArtifactStore

# browsers are installed inside the project venv (`PLAYWRIGHT_BROWSERS_PATH=0`), never globally
os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", "0")

AssertKind = Literal["visible", "hidden", "text", "value", "url", "title", "count"]


class Target(BaseModel):
    """How to find an element; prefer role+name, then label/text, then a CSS selector."""

    role: str | None = Field(default=None, description="ARIA role, e.g. button, textbox, link")
    name: str | None = Field(default=None, description="accessible name used with role")
    label: str | None = Field(default=None, description="form field label text")
    text: str | None = Field(default=None, description="visible text")
    selector: str | None = Field(default=None, description="CSS selector (last resort)")

    def describe(self) -> dict:
        return {k: v for k, v in self.model_dump().items() if v}


class Verdict(BaseModel):
    status: Literal["passed", "failed", "error"]
    failed_assertion: str | None = None
    error: str | None = None


class BrowserSession:
    """One browser context per case. All Playwright calls run on a single private thread, so the
    session can be driven from any caller thread (LangGraph tool nodes, request threads)."""

    def __init__(
        self,
        base_url: str,
        artifacts: ArtifactStore,
        *,
        headless: bool = True,
        timeout_ms: int = 5000,
        screenshots: bool = True,
    ):
        self.base_url = base_url.rstrip("/")
        self.artifacts = artifacts
        self.headless = headless
        self.timeout_ms = timeout_ms
        self.screenshots = screenshots
        self.steps: list[dict] = []
        self.receipts: list[dict] = []
        self.files: list[dict] = []
        self._thread = ThreadPoolExecutor(max_workers=1, thread_name_prefix="browser")
        self._pw = self._browser = self._context = self.page = None

    # ------------------------------------------------------------ lifecycle
    def _call(self, fn, *args, **kwargs):
        return self._thread.submit(fn, *args, **kwargs).result()

    def start(self) -> BrowserSession:
        def _start():
            from playwright.sync_api import sync_playwright

            self._pw = sync_playwright().start()
            self._browser = self._pw.chromium.launch(headless=self.headless)
            self._context = self._browser.new_context(base_url=self.base_url + "/")
            self._context.tracing.start(screenshots=True, snapshots=True)
            self.page = self._context.new_page()
            self.page.set_default_timeout(self.timeout_ms)
            self.page.set_default_navigation_timeout(max(self.timeout_ms, 10000))

        self._call(_start)
        return self

    def close(self) -> list[dict]:
        def _close():
            if self._context is not None:
                with tempfile.TemporaryDirectory() as tmp:
                    trace = Path(tmp) / "trace.zip"
                    try:
                        self._context.tracing.stop(path=str(trace))
                        digest = self.artifacts.put(trace.read_bytes())
                        self.files.append({"kind": "trace", "name": "trace.zip", "sha256": digest})
                    except Exception:  # a broken trace must not hide the verdict
                        pass
                self._context.close()
            if self._browser is not None:
                self._browser.close()
            if self._pw is not None:
                self._pw.stop()

        try:
            self._call(_close)
        finally:
            self._thread.shutdown(wait=True)
        return self.files

    def __enter__(self):
        return self.start()

    def __exit__(self, *exc):
        self.close()

    # ------------------------------------------------------------ helpers
    def _locator(self, target: Target):
        page = self.page
        if target.role:
            return page.get_by_role(target.role, name=target.name) if target.name else page.get_by_role(target.role)
        if target.label:
            return page.get_by_label(target.label)
        if target.text:
            return page.get_by_text(target.text)
        if target.selector:
            return page.locator(target.selector)
        raise ValueError("target needs role, label, text or selector")

    def _screenshot(self) -> str | None:
        if not self.screenshots:
            return None
        try:
            return self.artifacts.put(self.page.screenshot())
        except Exception:
            return None

    def _step(self, action: str, target: Target | None, value: Any, fn) -> dict:
        def _run():
            from playwright.sync_api import Error as PlaywrightError
            from playwright.sync_api import TimeoutError as PlaywrightTimeout

            started = time.monotonic()
            step: dict[str, Any] = {
                "seq": len(self.steps) + 1,
                "action": action,
                "target": target.describe() if target else None,
                "value": value,
            }
            try:
                step["result"] = fn()
                step["status"] = "ok"
            except PlaywrightTimeout as exc:
                step["status"] = "error"
                step["result"] = f"timeout after {self.timeout_ms} ms: {_first_line(exc)}"
            except (PlaywrightError, ValueError) as exc:
                step["status"] = "error"
                step["result"] = _first_line(exc)
            step["screenshot_sha"] = self._screenshot()
            step["ms"] = int((time.monotonic() - started) * 1000)
            self.steps.append(step)
            return step

        return self._call(_run)

    # ------------------------------------------------------------ tools
    def goto(self, url: str) -> dict:
        def _go():
            absolute = re.match(r"^https?://", url)
            self.page.goto(url if absolute else url.lstrip("/"))
            return self.page.url

        return self._step("goto", None, url, _go)

    def click(self, target: Target) -> dict:
        return self._step("click", target, None, lambda: self._locator(target).click())

    def fill(self, target: Target, value: str) -> dict:
        return self._step("fill", target, value, lambda: self._locator(target).fill(value))

    def select(self, target: Target, value: str) -> dict:
        return self._step("select", target, value, lambda: self._locator(target).select_option(value))

    def press(self, target: Target, key: str) -> dict:
        return self._step("press", target, key, lambda: self._locator(target).press(key))

    def read(self, target: Target) -> dict:
        return self._step("read", target, None, lambda: self._locator(target).first.inner_text())

    def assert_(self, kind: AssertKind, expected: str | None = None, target: Target | None = None) -> dict:
        """Evaluates one assertion and records a receipt. A missing element is a failed
        assertion (not an error): the receipt shows the actual state. A text assertion without
        a target checks the whole page body."""
        if target is None and kind == "text":
            target = Target(selector="body")

        def evaluate() -> dict:
            from playwright.sync_api import TimeoutError as PlaywrightTimeout

            actual: Any
            if kind == "url":
                actual = self.page.url
                passed = expected is not None and expected in actual
            elif kind == "title":
                actual = self.page.title()
                passed = expected is not None and expected in actual
            else:
                if target is None:
                    raise ValueError(f"assertion '{kind}' needs a target")
                loc = self._locator(target)
                if kind == "count":
                    actual = loc.count()
                    passed = str(actual) == str(expected)
                elif kind == "hidden":
                    actual = "hidden" if loc.count() == 0 or not loc.first.is_visible() else "visible"
                    passed = actual == "hidden"
                else:
                    try:
                        loc.first.wait_for(state="visible", timeout=self.timeout_ms)
                    except PlaywrightTimeout:
                        actual, passed = None, False
                    else:
                        if kind == "visible":
                            actual, passed = "visible", True
                        elif kind == "text":
                            actual = loc.first.inner_text()
                            passed = expected is not None and expected in actual
                        else:  # value
                            actual = loc.first.input_value()
                            passed = actual == expected
            receipt = {
                "kind": kind,
                "target": target.describe() if target else None,
                "expected": expected,
                "actual": actual,
                "passed": passed,
            }
            self.receipts.append({**receipt, "seq": len(self.steps) + 1})
            return receipt

        step = self._step("assert", target, expected, evaluate)
        if step["status"] == "ok":
            step["assertion"] = "passed" if step["result"]["passed"] else "failed"
        return step

    # ------------------------------------------------------------ verdict
    def verdict(self) -> Verdict:
        errors = [s for s in self.steps if s["status"] == "error"]
        if errors:
            first = errors[0]
            return Verdict(status="error", error=f"step {first['seq']} {first['action']}: {first['result']}")
        if not self.receipts:
            return Verdict(status="error", error="NO_ASSERTION: the agent made no browser_assert")
        failed = [r for r in self.receipts if not r["passed"]]
        if failed:
            r = failed[0]
            where = f" {r['target']}" if r["target"] else ""
            text = f"assert {r['kind']}{where}: expected {r['expected']!r}, actual {r['actual']!r}"
            return Verdict(status="failed", failed_assertion=text)
        return Verdict(status="passed")


def _first_line(exc: Exception) -> str:
    return str(exc).strip().splitlines()[0][:300] if str(exc).strip() else type(exc).__name__


# ---------------------------------------------------------------- agent tool specs
class GotoArgs(BaseModel):
    url: str = Field(description="path relative to the environment base URL, e.g. /orders/new")


class TargetArgs(BaseModel):
    target: Target


class FillArgs(BaseModel):
    target: Target
    value: str


class PressArgs(BaseModel):
    target: Target
    key: str = Field(description="e.g. Enter")


class AssertArgs(BaseModel):
    kind: AssertKind = Field(
        description="visible|hidden|text (contains; without target = whole page)|value|url (contains)|title|count"
    )
    target: Target | None = None
    expected: str | None = None


BROWSER_TOOLS = (
    "browser_goto",
    "browser_click",
    "browser_fill",
    "browser_select",
    "browser_press",
    "browser_read",
    "browser_assert",
)


def register_browser_tools(registry) -> None:
    from testagent.agent.tools import ToolSpec, to_text

    def session(ctx: dict) -> BrowserSession:
        browser = ctx.get("resources", {}).get("browser")
        if browser is None:
            raise ValueError("no browser session for this run")
        return browser

    def reply(step: dict) -> str:
        slim = {k: v for k, v in step.items() if k not in ("screenshot_sha",)}
        if step["status"] == "error":
            return "Error: " + to_text(slim)
        return to_text(slim)

    def _t(raw) -> Target:
        return raw if isinstance(raw, Target) else Target.model_validate(raw)

    specs = [
        (
            "browser_goto",
            "Open a page (relative to base URL).",
            GotoArgs,
            lambda ctx, url: reply(session(ctx).goto(url)),
        ),
        (
            "browser_click",
            "Click an element.",
            TargetArgs,
            lambda ctx, target: reply(session(ctx).click(_t(target))),
        ),
        (
            "browser_fill",
            "Fill an input.",
            FillArgs,
            lambda ctx, target, value: reply(session(ctx).fill(_t(target), value)),
        ),
        (
            "browser_select",
            "Select an option in a <select>.",
            FillArgs,
            lambda ctx, target, value: reply(session(ctx).select(_t(target), value)),
        ),
        (
            "browser_press",
            "Press a key on an element.",
            PressArgs,
            lambda ctx, target, key: reply(session(ctx).press(_t(target), key)),
        ),
        (
            "browser_read",
            "Read the text of an element.",
            TargetArgs,
            lambda ctx, target: reply(session(ctx).read(_t(target))),
        ),
        (
            "browser_assert",
            "Check an expected result. Only these receipts decide pass/fail; call it for every "
            "expected result of the case.",
            AssertArgs,
            lambda ctx, kind, target=None, expected=None: reply(
                session(ctx).assert_(kind, expected, _t(target) if target else None)
            ),
        ),
    ]
    for name, desc, schema, func in specs:
        registry.register(ToolSpec(name, "browser", desc, schema, func, writes=True, needs_ctx=True))
