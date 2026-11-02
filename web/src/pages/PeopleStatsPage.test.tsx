import { fireEvent, screen, waitFor } from "@testing-library/react";

import { mockFetch, renderPage } from "../test/utils";
import { PeopleStatsPage } from "./PeopleStatsPage";

afterEach(() => vi.unstubAllGlobals());

const people = [
  {
    person_id: "p1",
    name: "Lee Dev",
    active: true,
    attributed_count: 2,
    attributed_score: 13,
    attributed_by_role: { developer: { count: 2, score: 13 } },
    related_count: 3,
    requirements: [{ code: "REQ-001", title: "Place order", count: 2 }],
  },
  {
    person_id: "p2",
    name: "Pat Product",
    active: false,
    attributed_count: 1,
    attributed_score: 5,
    attributed_by_role: { owner: { count: 1, score: 5 } },
    related_count: 3,
    requirements: [],
  },
];

describe("PeopleStatsPage", () => {
  it("ranks people, drills down to defects, and saves severity weights", async () => {
    const urls: string[] = [];
    const calls = mockFetch({
      "GET /suts": () => ({ body: [] }),
      "GET /settings/severity-weights": () => ({ body: { critical: 8, major: 3, minor: 1, trivial: 0.1 } }),
      "GET /settings/severity-weights/defaults": () => ({ body: { critical: 10, major: 3, minor: 1, trivial: 0.1 } }),
      "PUT /settings/severity-weights": (init) => ({ body: JSON.parse(String(init.body)) }),
      "GET /stats/people": (init) => {
        urls.push(init.url);
        return { body: people };
      },
    });
    renderPage(<PeopleStatsPage />, { path: "/stats/people", route: "/stats/people?sort=related_count" });
    expect(await screen.findByText("Lee Dev")).toBeTruthy();
    expect(urls[0]).toContain("sort=related_count");
    expect(screen.getByText("Developer 2 (13)")).toBeTruthy();
    expect(screen.getByText("Disabled")).toBeTruthy();
    const link = screen.getByRole("link", { name: "Lee Dev" });
    expect(link.getAttribute("href")).toBe("/defects?person_id=p1");

    await waitFor(() => expect((screen.getByLabelText("Critical") as HTMLInputElement).value).toBe("8"));
    expect(await screen.findByText(/default Critical 10 \/ Major 3 \/ Minor 1 \/ Trivial 0.1/)).toBeTruthy();
    fireEvent.change(screen.getByLabelText("Critical"), { target: { value: "20" } });
    fireEvent.click(screen.getByRole("button", { name: "Save weights" }));
    await waitFor(() => expect(calls.some((c) => c.method === "PUT")).toBe(true));
    expect(calls.find((c) => c.method === "PUT")!.body).toEqual({ critical: 20, major: 3, minor: 1, trivial: 0.1 });
    fireEvent.click(screen.getByRole("button", { name: "Fill in defaults" }));
    await waitFor(() => expect((screen.getByLabelText("Critical") as HTMLInputElement).value).toBe("10"));
  });
});
