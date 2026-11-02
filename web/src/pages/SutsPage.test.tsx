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
    expect(screen.getByTestId("sut-explainer").textContent).toContain("The system under test (SUT) is the software you want to test");

    fireEvent.click(screen.getByRole("button", { name: /New SUT/ }));
    fireEvent.change(await screen.findByLabelText("Code"), { target: { value: "shop" } });
    fireEvent.change(screen.getByLabelText("Name"), { target: { value: "Shop" } });
    fireEvent.click(screen.getByRole("button", { name: /OK/ }));

    await waitFor(() => expect(calls.some((c) => c.method === "POST")).toBe(true));
    expect(calls.find((c) => c.method === "POST")!.body).toMatchObject({ code: "shop", name: "Shop" });
    expect(await screen.findByText("Shop (shop)")).toBeTruthy();
  });

  it("shows field validation without calling the API", async () => {
    const calls = mockFetch({ "GET /suts": () => ({ body: [] }) });
    renderPage(<SutsPage />);
    expect(await screen.findByText("No SUT yet")).toBeTruthy(); // helpful empty state
    fireEvent.click((await screen.findAllByRole("button", { name: /New SUT/ }))[1]);
    fireEvent.change(await screen.findByLabelText("Code"), { target: { value: "1bad" } });
    fireEvent.click(screen.getByRole("button", { name: /OK/ }));
    expect(await screen.findByText("Starts with a letter; digits, - and _ allowed")).toBeTruthy();
    expect(calls.every((c) => c.method === "GET")).toBe(true);
  });
});
