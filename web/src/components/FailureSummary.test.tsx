import { fireEvent, screen } from "@testing-library/react";

import { renderPage } from "../test/utils";
import type { FailureSummary as Summary } from "../api/types";
import { FailureSummary } from "./FailureSummary";

const summary: Summary = {
  kind: "assertion",
  cause: "sut",
  headline: "Expected status 201, got 422",
  expected: "201",
  actual: "422",
  step: "Submit the order",
  requirement_refs: [{ id: "r1", code: "REQ-001", title: "Place order", rule: null }],
  agent_note: "The amount field is rejected",
  next_actions: [],
} as unknown as Summary;

describe("FailureSummary", () => {
  it("shows cause, sentence, expected/actual, requirement and folds the raw output", async () => {
    renderPage(<FailureSummary summary={summary} raw={"Traceback (most recent call last)\nAssertionError"} versionId="v1" />);
    expect(screen.getByText("Suspected system issue")).toBeTruthy();
    expect(screen.getByText("Assertion failed")).toBeTruthy();
    expect(screen.getByText("Expected status 201, got 422")).toBeTruthy();
    expect(screen.getByText("201")).toBeTruthy();
    expect(screen.getByText("422")).toBeTruthy();
    expect(screen.getByRole("link", { name: "REQ-001" }).getAttribute("href")).toBe("/versions/v1?req=r1");
    expect(screen.getByText("Agent: The amount field is rejected")).toBeTruthy();
    expect(screen.queryByText(/Traceback/)).toBeNull();
    fireEvent.click(screen.getByText("Raw error output"));
    expect(await screen.findByText(/Traceback/)).toBeTruthy();
  });

  it("labels platform problems as not a system issue", () => {
    renderPage(<FailureSummary summary={{ ...summary, kind: "platform", cause: "platform", headline: "No environment", expected: null, actual: null, requirement_refs: [] } as unknown as Summary} />);
    expect(screen.getByText("Platform / configuration issue")).toBeTruthy();
    expect(screen.queryByText("Expected")).toBeNull();
  });
});
