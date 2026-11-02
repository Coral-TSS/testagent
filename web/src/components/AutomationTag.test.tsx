import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { AutomationTag } from "./AutomationTag";

describe("AutomationTag", () => {
  it("shows queue, generation, bound, needs-fix, env-down and not-automated states", () => {
    const { rerender } = render(<AutomationTag row={{ mode: "manual" }} job="queued" />);
    expect(screen.getByText("Queued")).toBeTruthy();
    rerender(<AutomationTag row={{ mode: "manual" }} job="running" />);
    expect(screen.getByText("Generating")).toBeTruthy();
    rerender(<AutomationTag row={{ mode: "automated", automation_status: "ok" }} job="done" />);
    expect(screen.getByText("Bound")).toBeTruthy();
    rerender(<AutomationTag row={{ mode: "manual", automation_status: "needs_fix", automation_note: "Assertion failed" }} />);
    expect(screen.getByText("Needs fix")).toBeTruthy();
    rerender(<AutomationTag row={{ mode: "manual", automation_status: "env_unavailable" }} />);
    expect(screen.getByText("Env unavailable")).toBeTruthy();
    rerender(<AutomationTag row={{ mode: "manual" }} />);
    expect(screen.getByText("Not automated")).toBeTruthy();
  });
});
