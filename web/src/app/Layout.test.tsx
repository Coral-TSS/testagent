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
            { kind: "strategy", id: "v1", label: "Test strategy & tasks", path: "/versions/v1?tab=strategy" },
            { kind: "task", id: "t1", label: "Regression task", path: "/tasks/t1" },
          ],
        },
      }),
      "GET /suts/s1/progress": () => ({ body: progress }),
    });
    renderPage(<Layout />, { path: "*", route: "/tasks/t1" });
    expect((await screen.findByRole("link", { name: "Test strategy & tasks" })).getAttribute("href")).toBe("/versions/v1?tab=strategy");
    expect(screen.getByRole("link", { name: "Version v1" })).toBeTruthy();
    expect(await screen.findByTestId("flow-steps")).toBeTruthy();
  });
});
