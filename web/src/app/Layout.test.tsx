import { screen } from "@testing-library/react";

import { progress } from "../test/navigationFixtures";
import { mockFetch, renderPage } from "../test/utils";
import { Layout } from "./Layout";

describe("Layout", () => {
  it("shows breadcrumbs from the object context and the main-flow bar", async () => {
    mockFetch({
      "GET /suts": () => ({ body: [{ id: "s1", code: "PROC", name: "Procurement system" }] }),
      "GET /nav/context": () => ({
        body: {
          sut: { id: "s1", code: "PROC", name: "Procurement system" },
          version: { id: "v1", name: "v1", status: "frozen" },
          crumbs: [
            { kind: "sut", id: "s1", label: "Procurement system (PROC)", path: "/suts/s1" },
            { kind: "version", id: "v1", label: "Version v1", path: "/versions/v1" },
            { kind: "strategy", id: "v1", label: "测试策略与任务", path: "/versions/v1?tab=strategy" },
            { kind: "task", id: "t1", label: "Regression task", path: "/tasks/t1" },
          ],
        },
      }),
      "GET /suts/s1/progress": () => ({ body: progress }),
    });
    renderPage(<Layout />, { path: "*", route: "/tasks/t1" });
    expect((await screen.findByRole("link", { name: "测试策略与任务" })).getAttribute("href")).toBe("/versions/v1?tab=strategy");
    expect(screen.getByRole("link", { name: "Version v1" })).toBeTruthy();
    expect(await screen.findByTestId("flow-steps")).toBeTruthy();
  });

  it("keeps one sidebar and highlights the workflow stage", async () => {
    mockFetch({
      "GET /suts": () => ({ body: [{ id: "s1", code: "PROC", name: "Procurement system" }, { id: "s2", code: "SHOP", name: "Shop" }] }),
      "GET /nav/context": () => ({ body: { sut: { id: "s1", code: "PROC", name: "Procurement system" }, version: { id: "v1", name: "v1", status: "frozen" }, crumbs: [] } }),
      "GET /suts/s1/progress": () => ({ body: progress }),
    });
    renderPage(<Layout />, { path: "*", route: "/versions/v1/model" });
    const all = await screen.findByRole("link", { name: "全部被测系统" });
    expect(all.getAttribute("href")).toBe("/suts");
    const model = await screen.findByRole("link", { name: "模型图谱" });
    expect(model.getAttribute("href")).toBe("/versions/v1/model");
    expect(model.closest(".ant-menu-item")?.className).toContain("ant-menu-item-selected");
    expect(screen.getByText("当前系统")).toBeTruthy();
    expect(screen.getByLabelText("切换被测系统")).toBeTruthy();
    expect(screen.getByLabelText("切换当前版本")).toBeTruthy();
    expect((await screen.findByRole("link", { name: "版本与需求" })).getAttribute("href")).toBe("/versions/v1");
    expect(screen.getByRole("link", { name: "策略" }).getAttribute("href")).toBe("/versions/v1/strategy");
    expect(screen.getByRole("link", { name: "任务" }).getAttribute("href")).toBe("/versions/v1/tasks");
    expect(screen.getByRole("link", { name: "用例" }).getAttribute("href")).toBe("/suts/s1/cases?version_id=v1");
    expect(screen.queryByRole("link", { name: "模型评审" })).toBeNull();
    expect(screen.getByRole("link", { name: "API 注册表" }).getAttribute("href")).toBe("/versions/v1/apis");
    expect(screen.getAllByRole("link", { name: "执行" }).map((el) => el.getAttribute("href"))).toEqual(["/executions"]);
    expect(screen.getAllByRole("link", { name: "缺陷" }).map((el) => el.getAttribute("href"))).toEqual(["/defects"]);
    const current = screen.getByText("当前系统").closest(".ant-menu-submenu");
    expect(current?.className).toContain("ant-menu-submenu");
    expect(current?.className).not.toContain("ant-menu-item-group");
    expect(screen.getByRole("link", { name: "测试报告" }).getAttribute("href")).toBe("/reports?sut_id=s1&version_id=v1");
    expect(screen.getAllByText("人员").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Agent").length).toBeGreaterThan(0);
    expect(screen.queryByRole("link", { name: "测试用例" })).toBeNull();
    expect(screen.getByLabelText("切换被测系统")).toBeTruthy();
    expect(screen.queryByRole("menuitem", { name: "PROC" })).toBeNull();
    expect(screen.queryByRole("link", { name: "请先选择被测系统" })).toBeNull();
  });

  it("keeps the system list as its own entry and hides modeling until a system is open", async () => {
    mockFetch({ "GET /suts": () => ({ body: [{ id: "s1", code: "PROC", name: "Procurement system" }] }) });
    renderPage(<Layout />, { path: "*", route: "/suts" });
    const all = await screen.findByRole("link", { name: "全部被测系统" });
    expect(all.getAttribute("href")).toBe("/suts");
    expect(all.closest(".ant-menu-item")?.className).toContain("ant-menu-item-selected");
    expect(screen.getByText("当前系统")).toBeTruthy();
    expect(screen.queryByRole("link", { name: "模型图谱" })).toBeNull();
    expect(screen.getByText("建模").closest(".ant-menu-item")?.className).toContain("ant-menu-item-disabled");
  });
});
