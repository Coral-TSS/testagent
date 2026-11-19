import { routeObject, withContext } from "./navContext";

describe("routeObject", () => {
  it("maps detail pages to the object shown", () => {
    expect(routeObject("/suts/s1/model", "")).toMatchObject({ kind: "sut", id: "s1", page: "模型" });
    expect(routeObject("/suts/s1/review", "?version_id=v1")).toMatchObject({ kind: "sut", versionId: "v1", page: "模型评审" });
    expect(routeObject("/versions/v1", "?tab=strategy")).toEqual({ kind: "version", id: "v1", page: "测试策略与任务" });
    expect(routeObject("/versions/v1", "?req=r1")).toEqual({ kind: "requirement", id: "r1" });
    expect(routeObject("/cases/c1", "")).toEqual({ kind: "case", id: "c1" });
    expect(routeObject("/runs/x", "")).toEqual({ kind: "run", id: "x" });
    expect(routeObject("/executions/e", "")).toEqual({ kind: "execution", id: "e" });
  });

  it("reads the current SUT / version of list pages from the query string", () => {
    expect(routeObject("/defects", "?sut_id=s1&version_id=v1")).toMatchObject({ kind: "version", id: "v1", page: "缺陷", sutId: "s1" });
    expect(routeObject("/cases", "?sut=s1")).toMatchObject({ kind: "sut", id: "s1", page: "测试用例" });
    expect(routeObject("/reports", "")).toEqual({ page: "报告" });
    expect(routeObject("/agent/config", "")).toEqual({});
  });

  it("keeps the context in global links", () => {
    expect(withContext("/defects", "s1", "v1")).toBe("/defects?sut_id=s1&version_id=v1");
    expect(withContext("/cases", "s1", "v1")).toBe("/cases?sut=s1");
    expect(withContext("/reports")).toBe("/reports");
  });
});
