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
      <output aria-label="当前页">{location.pathname + location.search}</output>
      <button onClick={() => navigate(-1)}>返回</button>
    </>
  );
}

describe("main-flow step navigation (#12)", () => {
  it.each(["click", "Enter", "Space"])("opens the current step with %s", async (input) => {
    const user = userEvent.setup();
    renderPage(<FlowNavigation />, { path: "*", route: "/start" });
    const step = screen.getByRole("button", { name: /策略草稿/ });

    if (input === "click") {
      await user.click(step);
    } else {
      step.focus();
      await user.keyboard(input === "Enter" ? "{Enter}" : " ");
    }

    expect(screen.getByLabelText("当前页").textContent).toBe("/versions/v1?tab=strategy");
    await user.click(screen.getByRole("button", { name: "返回" }));
    expect(screen.getByLabelText("当前页").textContent).toBe("/start");
  });

  it.each([
    ["completed", /模型 3 个实体/, "/suts/s1/model"],
    ["pending", /用例 0 个用例/, "/versions/v1?tab=cases"],
  ])("opens a %s step with a single history entry", async (_status, name, path) => {
    const user = userEvent.setup();
    renderPage(<FlowNavigation />, { path: "*", route: "/start" });
    await user.click(screen.getByRole("button", { name }));
    expect(screen.getByLabelText("当前页").textContent).toBe(path);
    await user.click(screen.getByRole("button", { name: "返回" }));
    expect(screen.getByLabelText("当前页").textContent).toBe("/start");
  });

  it("keeps steps navigable after the main flow is complete", async () => {
    const user = userEvent.setup();
    renderPage(<FlowNavigation value={{ ...progress, next: null }} />, { path: "*", route: "/start" });
    await user.click(screen.getByRole("button", { name: /策略草稿/ }));
    expect(screen.getByLabelText("当前页").textContent).toBe("/versions/v1?tab=strategy");
  });
});
