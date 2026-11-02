import { routeObject, withContext } from "./navContext";

describe("routeObject", () => {
  it("maps detail pages to the object shown", () => {
    expect(routeObject("/suts/s1/model", "")).toMatchObject({ kind: "sut", id: "s1", page: "Model" });
    expect(routeObject("/suts/s1/review", "?version_id=v1")).toMatchObject({ kind: "sut", versionId: "v1", page: "Model review" });
    expect(routeObject("/versions/v1", "?tab=strategy")).toEqual({ kind: "version", id: "v1", page: "Test strategy & tasks" });
    expect(routeObject("/versions/v1", "?req=r1")).toEqual({ kind: "requirement", id: "r1" });
    expect(routeObject("/cases/c1", "")).toEqual({ kind: "case", id: "c1" });
    expect(routeObject("/runs/x", "")).toEqual({ kind: "run", id: "x" });
    expect(routeObject("/executions/e", "")).toEqual({ kind: "execution", id: "e" });
  });

  it("reads the current SUT / version of list pages from the query string", () => {
    expect(routeObject("/defects", "?sut_id=s1&version_id=v1")).toMatchObject({ kind: "version", id: "v1", page: "Defect", sutId: "s1" });
    expect(routeObject("/cases", "?sut=s1")).toMatchObject({ kind: "sut", id: "s1", page: "Test cases" });
    expect(routeObject("/reports", "")).toEqual({ page: "Report" });
    expect(routeObject("/agent/config", "")).toEqual({});
  });

  it("keeps the context in global links", () => {
    expect(withContext("/defects", "s1", "v1")).toBe("/defects?sut_id=s1&version_id=v1");
    expect(withContext("/cases", "s1", "v1")).toBe("/cases?sut=s1");
    expect(withContext("/reports")).toBe("/reports");
  });
});
