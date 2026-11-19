import { fireEvent, screen, waitFor } from "@testing-library/react";

import { mockFetch, renderPage } from "../test/utils";
import { SutsPage } from "./SutsPage";

afterEach(() => vi.unstubAllGlobals());

describe("SutsPage", () => {
  it("lists systems and creates a new one", async () => {
    const rows = [{ id: "1", code: "procurement", name: "Procurement system", description: null }];
    const calls = mockFetch({
      "GET /suts": () => ({ body: rows }),
      "POST /suts": (init) => {
        const body = JSON.parse(String(init.body));
        rows.push({ id: "2", ...body, description: null });
        return { status: 201, body: rows[1] };
      },
    });
    renderPage(<SutsPage />);
    expect(await screen.findByText("Procurement system (procurement)")).toBeTruthy();
    expect(screen.getByTestId("sut-explainer").textContent).toContain("被测系统（SUT）是你要测试的软件");

    fireEvent.click(screen.getByRole("button", { name: /新建被测系统/ }));
    fireEvent.change(await screen.findByLabelText("编号"), { target: { value: "shop" } });
    fireEvent.change(screen.getByLabelText("名称"), { target: { value: "Shop" } });
    fireEvent.click(screen.getByRole("button", { name: /确定/ }));

    await waitFor(() => expect(calls.some((c) => c.method === "POST")).toBe(true));
    expect(calls.find((c) => c.method === "POST")!.body).toMatchObject({ code: "shop", name: "Shop" });
    expect(await screen.findByText("Shop (shop)")).toBeTruthy();
  });

  it("shows field validation without calling the API", async () => {
    const calls = mockFetch({ "GET /suts": () => ({ body: [] }) });
    renderPage(<SutsPage />);
    expect(await screen.findByText("暂无被测系统")).toBeTruthy(); // helpful empty state
    fireEvent.click((await screen.findAllByRole("button", { name: /新建被测系统/ }))[1]);
    fireEvent.change(await screen.findByLabelText("编号"), { target: { value: "1bad" } });
    fireEvent.click(screen.getByRole("button", { name: /确定/ }));
    expect(await screen.findByText("以字母开头；允许数字、- 和 _")).toBeTruthy();
    expect(calls.every((c) => c.method === "GET")).toBe(true);
  });
});
