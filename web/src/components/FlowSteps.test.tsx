import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useLocation, useNavigate } from "react-router-dom";

import type { SutProgress } from "../api/types";
import { progress } from "../test/navigationFixtures";
import { renderPage } from "../test/utils";
import { FlowSteps } from "./FlowSteps";

function FlowNavigation({ value = progress }: { value?: SutProgress }) {
  const location = useLocation();
  const navigate = useNavigate();
  return (
    <>
      <FlowSteps progress={value} />
      <output aria-label="Current page">{location.pathname + location.search}</output>
      <button onClick={() => navigate(-1)}>Back</button>
    </>
  );
}

describe("main-flow step navigation (#12)", () => {
  it.each(["click", "Enter", "Space"])("opens the current step with %s", async (input) => {
    const user = userEvent.setup();
    renderPage(<FlowNavigation />, { path: "*", route: "/start" });
    const step = screen.getByRole("button", { name: /Strategy draft/ });

    if (input === "click") {
      await user.click(step);
    } else {
      step.focus();
      await user.keyboard(input === "Enter" ? "{Enter}" : " ");
    }

    expect(screen.getByLabelText("Current page").textContent).toBe("/versions/v1?tab=strategy");
    await user.click(screen.getByRole("button", { name: "Back" }));
    expect(screen.getByLabelText("Current page").textContent).toBe("/start");
  });

  it.each([
    ["completed", /Model 3 entities/, "/suts/s1/model"],
    ["pending", /Cases 0 case\(s\)/, "/versions/v1?tab=cases"],
  ])("opens a %s step with a single history entry", async (_status, name, path) => {
    const user = userEvent.setup();
    renderPage(<FlowNavigation />, { path: "*", route: "/start" });
    await user.click(screen.getByRole("button", { name }));
    expect(screen.getByLabelText("Current page").textContent).toBe(path);
    await user.click(screen.getByRole("button", { name: "Back" }));
    expect(screen.getByLabelText("Current page").textContent).toBe("/start");
  });

  it("keeps steps navigable after the main flow is complete", async () => {
    const user = userEvent.setup();
    renderPage(<FlowNavigation value={{ ...progress, next: null }} />, { path: "*", route: "/start" });
    await user.click(screen.getByRole("button", { name: /Strategy draft/ }));
    expect(screen.getByLabelText("Current page").textContent).toBe("/versions/v1?tab=strategy");
  });
});
