import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { AutomationTag } from "./AutomationTag";

describe("AutomationTag", () => {
  it("shows queue, generation, bound, needs-fix, env-down and not-automated states", () => {
    const { rerender } = render(<AutomationTag row={{ mode: "manual" }} job="queued" />);
    expect(screen.getByText("排队中")).toBeTruthy();
    rerender(<AutomationTag row={{ mode: "manual" }} job="running" />);
    expect(screen.getByText("生成中")).toBeTruthy();
    rerender(<AutomationTag row={{ mode: "automated", automation_status: "ok" }} job="done" />);
    expect(screen.getByText("已绑定")).toBeTruthy();
    rerender(<AutomationTag row={{ mode: "manual", automation_status: "needs_fix", automation_note: "断言失败" }} />);
    expect(screen.getByText("待修复")).toBeTruthy();
    rerender(<AutomationTag row={{ mode: "manual", automation_status: "env_unavailable" }} />);
    expect(screen.getByText("环境不可用")).toBeTruthy();
    rerender(<AutomationTag row={{ mode: "manual" }} />);
    expect(screen.getByText("未自动化")).toBeTruthy();
  });
});
