import { useQueryClient } from "@tanstack/react-query";
import { fireEvent, screen, waitFor, within } from "@testing-library/react";

import type { CaseRow, Suggestion, Version } from "../api/types";
import { VersionPage } from "../pages/VersionPage";
import { mockFetch, renderPage } from "../test/utils";
import { CaseList } from "./CaseList";
import { StrategyTab } from "./StrategyTab";
import { SuggestionList } from "./SuggestionList";

afterEach(() => vi.unstubAllGlobals());

function cases(count: number): CaseRow[] {
  return Array.from({ length: count }, (_, index) => ({
    id: `c${index + 1}`, code: `TC-${String(index + 1).padStart(3, "0")}`, title: `Case ${index + 1}`,
    priority: "P1", type_tag: "functional", mode: "manual", status: "draft", source: "human", revision: 1,
    requirement_codes: [], node_count: 0, category: index === 0 ? "requirement" : "quality",
  }));
}

describe("list quantities and paging (#1/#2)", () => {
  it("keeps the full case count when moving between pages", async () => {
    mockFetch({
      "GET /suts/s1/cases": () => ({ body: cases(65) }),
      "GET /suts/s1/environments": () => ({ body: [] }),
    });
    renderPage(<CaseList sutId="s1" />);
    await waitFor(() => expect(screen.getByRole("status", { name: "Test cases count" }).textContent).toBe("Test cases (65)"));
    expect(screen.getByRole("region", { name: "Test cases rows" }).tabIndex).toBe(0);
    expect(screen.getByText("Total 65 items")).toBeTruthy();
    expect(screen.queryByText("TC-065")).toBeNull();
    fireEvent.click(screen.getByTitle("2"));
    expect(await screen.findByText("TC-065")).toBeTruthy();
    expect(screen.getByRole("status", { name: "Test cases count" }).textContent).toBe("Test cases (65)");
  });

  it("shows server search results against the unfiltered total, including zero matches", async () => {
    mockFetch({
      "GET /suts/s1/cases": ({ url }) => ({ body: url.includes("q=pair") ? cases(2) : url.includes("q=missing") ? [] : cases(65) }),
      "GET /suts/s1/environments": () => ({ body: [] }),
    });
    renderPage(<CaseList sutId="s1" />);
    await screen.findByText("Total 65 items");
    const search = screen.getByPlaceholderText("Code/title/test point");
    fireEvent.change(search, { target: { value: "pair" } });
    fireEvent.keyDown(search, { key: "Enter", keyCode: 13 });
    fireEvent.keyUp(search, { key: "Enter", keyCode: 13 });
    expect(await screen.findByText("2 / 65 total")).toBeTruthy();
    fireEvent.change(search, { target: { value: "missing" } });
    fireEvent.keyDown(search, { key: "Enter", keyCode: 13 });
    fireEvent.keyUp(search, { key: "Enter", keyCode: 13 });
    await waitFor(() => expect(screen.getByRole("status", { name: "Test cases total" }).textContent).toBe("0 / 65 total"));
    expect(screen.getByText("No cases match the filters")).toBeTruthy();
  });

  it("keeps category counts correct when data refreshes under an active filter", async () => {
    let rows = cases(3);
    mockFetch({ "GET /suts/s1/cases": () => ({ body: rows }), "GET /suts/s1/environments": () => ({ body: [] }) });
    function Page() {
      const client = useQueryClient();
      return <><CaseList sutId="s1" /><button onClick={() => client.invalidateQueries({ queryKey: ["cases"] })}>Refresh data</button></>;
    }
    renderPage(<Page />, { motion: false });
    await screen.findByText("Total 3 items");
    fireEvent.click(screen.getByRole("button", { name: "filter" }));
    fireEvent.click(within(await screen.findByRole("menu")).getByText("General quality"));
    fireEvent.click(screen.getByRole("button", { name: "OK" }));
    expect(await screen.findByText("2 / 3 total")).toBeTruthy();
    rows = cases(4);
    fireEvent.click(screen.getByRole("button", { name: "Refresh data" }));
    expect(await screen.findByText("3 / 4 total")).toBeTruthy();
    expect(screen.queryByText("TC-001")).toBeNull();
  });

  it("updates suggestion quantities when only AI inferences are shown", async () => {
    const items = [
      { id: "a", kind: "node", status: "pending", source: "requirement", payload: { name: "Account", node_kind: "entity" } },
      { id: "b", kind: "node", status: "pending", source: "ai_inferred", payload: { name: "Balance", node_kind: "entity" } },
      { id: "c", kind: "node", status: "pending", source: "requirement", payload: { name: "Payment", node_kind: "entity" } },
    ] as Suggestion[];
    renderPage(<SuggestionList sutId="s1" items={items} onChanged={() => {}} />);
    expect(screen.getByRole("status", { name: "Model suggestions count" }).textContent).toBe("Model suggestions (3)");
    fireEvent.click(screen.getByRole("switch", { name: "Only AI inferences" }));
    expect(screen.getByText("1 / 3 total")).toBeTruthy();
    expect(screen.queryByText(/“Account”/)).toBeNull();
  });

  it("counts requirements and tasks within their version", async () => {
    const version = { id: "v1", sut_id: "s1", name: "V1", status: "requirements_frozen" } as Version;
    mockFetch({
      "GET /versions/v1": () => ({ body: version }),
      "GET /versions/v1/requirements": () => ({ body: [{ id: "r1", code: "REQ-001", title: "Submit", status: "confirmed", priority: "P1" }, { id: "r2", code: "REQ-002", title: "Approve", status: "confirmed", priority: "P1" }] }),
      "GET /versions/v1/history": () => ({ body: [] }),
      "GET /suts/s1/suggestions": () => ({ body: [] }),
      "GET /versions/v1/strategy": () => ({ status: 404, body: { code: "NOT_FOUND" } }),
      "GET /versions/v1/tasks": () => ({ body: [{ id: "t1", name: "Smoke", kind: "regression", executor: "agent", status: "draft", case_count: 0, latest_run: null }] }),
      "GET /versions/v1/gaps": () => ({ body: [] }),
      "GET /suts/s1/environments": () => ({ body: [] }),
    });
    renderPage(<><VersionPage /><StrategyTab version={version} onOpenRun={() => {}} /></>, { path: "/versions/:versionId", route: "/versions/v1" });
    await waitFor(() => expect(screen.getByRole("status", { name: "Requirements count" }).textContent).toBe("Requirements (2)"));
    expect(screen.getByRole("status", { name: "Tasks count" }).textContent).toBe("Tasks (1)");
    expect(screen.getByText("Total 2 items")).toBeTruthy();
    expect(screen.getByText("Total 1 item")).toBeTruthy();
  });

  it("shows a failed load as unavailable rather than an empty zero-count list, with retry", async () => {
    let failed = true;
    mockFetch({
      "GET /suts/s1/cases": () => failed ? ({ status: 503, body: { code: "UNAVAILABLE", message: "Offline" } }) : ({ body: cases(2) }),
      "GET /suts/s1/environments": () => ({ body: [] }),
    });
    renderPage(<CaseList sutId="s1" />);
    expect(await screen.findByText("Count unavailable")).toBeTruthy();
    expect(screen.queryByText("No cases yet")).toBeNull();
    expect(screen.queryByText("Total 0 items")).toBeNull();
    failed = false;
    fireEvent.click(screen.getByRole("button", { name: "Retry Test cases" }));
    expect(await screen.findByText("Total 2 items")).toBeTruthy();
  });
});
