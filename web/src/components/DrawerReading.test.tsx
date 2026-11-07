import { useState } from "react";
import { fireEvent, screen, waitFor, within } from "@testing-library/react";

import { mockFetch, renderPage } from "../test/utils";
import { AgentRunDrawer } from "./AgentRunDrawer";
import { NodeDrawer } from "./NodeDrawer";
import { RequirementDrawer } from "./RequirementDrawer";
import { ReadingDrawer } from "./ReadingDrawer";
import { ExpandableDescription } from "./ExpandableDescription";
import { VersionPage } from "../pages/VersionPage";
import { ModelPage } from "../pages/ModelPage";

const requirement = { id: "req1", code: "REQ-001", title: "Example requirement", priority: "P1", status: "draft", raw_text: "Original requirement", structured: {}, people: [], fields: [], links: [], cases: [], suggestions: [] };
const node = { id: "n1", name: "Submit request", kind: "action", description: "Full description", module_id: null, attributes: {}, apis: [], edges: [], links: [], inputs: [], outputs: [], preconditions: [], effects: [] };
const storageKey = "testagent:drawer-width:requirement";

function viewport(width: number) {
  Object.defineProperty(window, "innerWidth", { configurable: true, value: width });
  fireEvent(window, new Event("resize"));
}
function panelWidth() { return screen.getByRole("dialog").closest<HTMLElement>(".ant-drawer-content-wrapper")!.style.width; }
function requirementPage() {
  return renderPage(<RequirementDrawer reqId="req1" sutId="s1" locked={false} onClose={() => {}} onOpenRun={() => {}} />, { motion: false });
}
function fixtures() {
  return mockFetch({
    "GET /requirements/req1": () => ({ body: requirement }), "GET /suts/s1/graph": () => ({ body: { nodes: [], edges: [] } }),
    "GET /suts/s1/links": () => ({ body: [] }), "GET /suts/s1/fields": () => ({ body: [] }), "GET /persons": () => ({ body: [] }),
    "GET /nodes/n1": () => ({ body: node }), "GET /nodes/n1/references": () => ({ body: [] }), "GET /suts/s1/apis": () => ({ body: [] }),
    "GET /agent/runs/a1": () => ({ body: { id: "a1", purpose: "generate_cases", status: "succeeded", steps: [] } }),
    "PATCH /requirements/req1": () => ({ body: requirement }),
  });
}

beforeEach(() => { window.localStorage.clear(); viewport(1440); });
afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals(); window.localStorage.clear(); viewport(1024); });

it.each([
  ["requirement", () => <RequirementDrawer reqId="req1" sutId="s1" locked={false} onClose={() => {}} onOpenRun={() => {}} />],
  ["node", () => <NodeDrawer sutId="s1" nodeId="n1" modules={[]} allNodes={[]} onClose={() => {}} onOpenNode={() => {}} />],
  ["agent", () => <AgentRunDrawer runId="a1" onClose={() => {}} />],
] as const)("lets the %s drawer adapt and expose a keyboard resize handle", async (_, component) => {
  fixtures(); renderPage(component(), { motion: false });
  await screen.findByRole("dialog");
  expect(panelWidth()).toBe("864px");
  expect(screen.getByRole("separator", { name: "Resize drawer" }).getAttribute("aria-orientation")).toBe("vertical");
});

it("remembers keyboard resizing when reopened without saving the requirement", async () => {
  const calls = fixtures(); const first = requirementPage();
  await screen.findByDisplayValue("Original requirement");
  fireEvent.change(screen.getByLabelText("Requirement text"), { target: { value: "Unsaved requirement edits" } });
  fireEvent.keyDown(screen.getByRole("separator", { name: "Resize drawer" }), { key: "ArrowLeft" });
  expect(panelWidth()).toBe("896px");
  expect(screen.getByDisplayValue("Unsaved requirement edits")).toBeTruthy();
  expect(calls.some((c) => c.method !== "GET")).toBe(false);
  first.unmount(); requirementPage();
  await screen.findByRole("dialog");
  expect(panelWidth()).toBe("896px");
});

it("clamps to the viewport on small screens and restores the desktop preference", async () => {
  window.localStorage.setItem(storageKey, "1000"); fixtures(); requirementPage();
  await screen.findByRole("dialog"); expect(panelWidth()).toBe("1000px");
  viewport(360); await waitFor(() => expect(panelWidth()).toBe("360px"));
  expect(screen.queryByRole("separator", { name: "Resize drawer" })).toBeNull();
  viewport(1440); await waitFor(() => expect(panelWidth()).toBe("1000px"));
});

it("bounds keyboard resizing and can restore the responsive default", async () => {
  fixtures(); requirementPage(); await screen.findByRole("dialog");
  const handle = screen.getByRole("separator", { name: "Resize drawer" });
  fireEvent.keyDown(handle, { key: "Home" }); fireEvent.keyDown(handle, { key: "ArrowRight" }); expect(panelWidth()).toBe("480px");
  fireEvent.keyDown(handle, { key: "End" }); fireEvent.keyDown(handle, { key: "ArrowLeft" }); expect(panelWidth()).toBe("1392px");
  fireEvent.keyDown(handle, { key: "Enter" }); expect(panelWidth()).toBe("864px");
});

it("ignores invalid preferences and survives unavailable browser storage", async () => {
  window.localStorage.setItem(storageKey, "NaN"); fixtures(); requirementPage();
  await screen.findByRole("dialog"); expect(panelWidth()).toBe("864px");
  vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => { throw new Error("Storage unavailable"); });
  fireEvent.keyDown(screen.getByRole("separator", { name: "Resize drawer" }), { key: "ArrowLeft" });
  expect(panelWidth()).toBe("896px");
});

it("expands and collapses a model description without opening its drawer", async () => {
  const description = "This action validates the submitted request. ".repeat(8) + "FULL DESCRIPTION END";
  mockFetch({
    "GET /suts/s1/graph": () => ({ body: { nodes: [{ ...node, description }], edges: [] } }),
    "GET /suts/s1/modules": () => ({ body: [] }), "GET /suts/s1/fields": () => ({ body: [] }),
    "GET /suts/s1/links": () => ({ body: [] }), "GET /suts/s1/suggestions": () => ({ body: [] }),
  });
  renderPage(<ModelPage />, { path: "/suts/:sutId/model", route: "/suts/s1/model?view=list" });
  const expand = await screen.findByRole("button", { name: "Expand description of Submit request" });
  const row = expand.closest("tr")!;
  expect(within(row).queryByText(/FULL DESCRIPTION END/)).toBeNull();
  fireEvent.click(expand);
  expect(within(row).getByText(description)).toBeTruthy();
  expect(screen.queryByRole("dialog")).toBeNull();
  const collapse = screen.getByRole("button", { name: "Collapse description of Submit request" });
  expect(collapse.getAttribute("aria-expanded")).toBe("true");
  fireEvent.click(collapse);
  expect(within(row).queryByText(/FULL DESCRIPTION END/)).toBeNull();
});


it("closes with Escape when the resize handle has focus", async () => {
  const onClose = vi.fn();
  renderPage(<ReadingDrawer kind="requirement" open onClose={onClose} title="Example">Body</ReadingDrawer>, { motion: false });
  const handle = await screen.findByRole("separator", { name: "Resize drawer" });
  handle.focus(); fireEvent.keyDown(handle, { key: "Escape", keyCode: 27 });
  expect(onClose).toHaveBeenCalledOnce();
});

it("keeps different drawer types' width preferences separate", async () => {
  window.localStorage.setItem(storageKey, "1100");
  window.localStorage.setItem("testagent:drawer-width:node", "900");
  fixtures(); renderPage(<NodeDrawer sutId="s1" nodeId="n1" modules={[]} allNodes={[]} onClose={() => {}} onOpenNode={() => {}} />, { motion: false });
  await screen.findByRole("dialog"); expect(panelWidth()).toBe("900px");
});

it("opens and adjusts even when browser storage cannot be read", async () => {
  vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => { throw new Error("Storage blocked"); });
  fixtures(); requirementPage(); await screen.findByRole("dialog");
  fireEvent.keyDown(screen.getByRole("separator", { name: "Resize drawer" }), { key: "ArrowRight" });
  expect(panelWidth()).toBe("832px");
});

it("collapses changed descriptions and does not offer expansion for short or empty text", () => {
  function Page() {
    const [text, setText] = useState("Long description ".repeat(25));
    return <><ExpandableDescription name="Example" text={text} /><button onClick={() => setText("Other description ".repeat(25))}>Change text</button><button onClick={() => setText("Short")}>Short text</button><button onClick={() => setText("")}>Empty text</button></>;
  }
  renderPage(<Page />);
  fireEvent.click(screen.getByRole("button", { name: "Expand description of Example" }));
  expect(screen.getByRole("button", { name: "Collapse description of Example" })).toBeTruthy();
  fireEvent.click(screen.getByText("Change text"));
  expect(screen.getByRole("button", { name: "Expand description of Example" }).getAttribute("aria-expanded")).toBe("false");
  fireEvent.click(screen.getByText("Short text"));
  expect(screen.queryByRole("button", { name: /description of Example/ })).toBeNull();
  expect(screen.getByText("Short")).toBeTruthy();
  fireEvent.click(screen.getByText("Empty text"));
  expect(screen.queryByRole("button", { name: /description of Example/ })).toBeNull();
  expect(screen.getByText("—")).toBeTruthy();
});


it("associates the detail text label with its visible field when the create form is also mounted", async () => {
  mockFetch({
    "GET /versions/v1": () => ({ body: { id: "v1", sut_id: "s1", name: "V1", status: "planning" } }),
    "GET /versions/v1/requirements": () => ({ body: [requirement] }), "GET /versions/v1/history": () => ({ body: [] }),
    "GET /requirements/req1": () => ({ body: requirement }), "GET /suts/s1/graph": () => ({ body: { nodes: [], edges: [] } }),
    "GET /suts/s1/links": () => ({ body: [] }), "GET /suts/s1/fields": () => ({ body: [] }), "GET /persons": () => ({ body: [] }), "GET /suts/s1/suggestions": () => ({ body: [] }),
  });
  renderPage(<VersionPage />, { path: "/versions/:versionId", route: "/versions/v1?req=req1", motion: false });
  const dialog = await screen.findByRole("dialog");
  const label = await within(dialog).findByText("Requirement text", { selector: "label" });
  expect((label as HTMLLabelElement).control?.closest('[role="dialog"]')).toBe(dialog);
});
