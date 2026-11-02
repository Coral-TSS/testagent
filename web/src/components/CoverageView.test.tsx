import { render, screen } from "@testing-library/react";

import { CoverageView } from "./CoverageView";

describe("CoverageView", () => {
  it("shows ratios, uncovered lists and distributions", () => {
    render(
      <CoverageView
        coverage={{
          version_id: "v",
          cases: 2,
          requirements: {
            total: 3,
            covered: 2,
            uncovered: [{ id: "r3", code: "REQ-003", title: "Export purchase orders" }],
            items: [],
          },
          actions: { total: 3, covered: 2, uncovered: [{ id: "a", name: "Export purchase orders" }], items: [] },
          by_priority: { P0: 1, P1: 1 },
          by_type: { functional: 2 },
          by_scenario: { boundary: 2 },
        }}
      />,
    );
    expect(screen.getByText("Requirement coverage 2/3")).toBeTruthy();
    expect(screen.getByText("REQ-003 Export purchase orders")).toBeTruthy();
    expect(screen.getByText("Action node coverage 2/3")).toBeTruthy();
    expect(screen.getByText("Boundary 2")).toBeTruthy();
    expect(screen.getByText("P0 1")).toBeTruthy();
  });
});
