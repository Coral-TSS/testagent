import { fireEvent, screen } from "@testing-library/react";

import { progress } from "../test/navigationFixtures";
import { renderPage } from "../test/utils";
import { EmptyState } from "./EmptyState";
import { FlowSteps } from "./FlowSteps";
import { objLabel, ObjLink, PathText } from "./ObjLink";
import { OnboardingChecklist } from "./OnboardingChecklist";
import { SutExplainer } from "./SutExplainer";

describe("navigation components", () => {
  it("labels objects as Name (code)", () => {
    expect(objLabel("Create purchase order", "REQ-001")).toBe("Create purchase order (REQ-001)");
    expect(objLabel("Create purchase order", null)).toBe("Create purchase order");
    renderPage(<ObjLink to="/cases/c1" name="Amount approval" code="TC-001" />);
    expect(screen.getByRole("link", { name: "Amount approval (TC-001)" }).getAttribute("href")).toBe("/cases/c1");
  });

  it("shows an absolute path with a copy button", async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, "clipboard", { value: { writeText }, configurable: true });
    renderPage(<PathText path="D:/TestAgent/runtime/repos/PROC" />);
    expect(screen.getByText("D:/TestAgent/runtime/repos/PROC")).toBeTruthy();
    fireEvent.click(screen.getByLabelText("Copy path"));
    expect(writeText).toHaveBeenCalledWith("D:/TestAgent/runtime/repos/PROC");
  });

  it("renders an empty state with a primary action", () => {
    const onAction = vi.fn();
    renderPage(<EmptyState title="No environment yet" hint="Add an environment first" actionLabel="Add environment" onAction={onAction} />);
    expect(screen.getByText("No environment yet")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Add environment" }));
    expect(onAction).toHaveBeenCalled();
  });

  it("shows the main flow with step states and the next action", () => {
    renderPage(<FlowSteps progress={progress} />);
    const bar = screen.getByTestId("flow-steps");
    for (const t of ["SUT", "Model", "Requirements", "Strategy", "Tasks", "Cases", "Runs", "Results"]) {
      expect(bar.textContent).toContain(t);
    }
    expect(screen.getByRole("button", { name: /Create\/confirm test strategy/ })).toBeTruthy();
    expect(bar.querySelectorAll(".ant-steps-item-finish").length).toBe(3);
  });

  it("explains what a SUT is and lists the onboarding steps", () => {
    renderPage(
      <>
        <SutExplainer repoPath={progress.repo_path} />
        <OnboardingChecklist progress={progress} />
      </>,
    );
    expect(screen.getByTestId("sut-explainer").textContent).toContain("D:/TestAgent/runtime/repos/PROC");
    expect(screen.getByTestId("onboarding").textContent).toContain("2 requirements · frozen");
  });
});
