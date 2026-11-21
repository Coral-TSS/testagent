import { menuSelection, switchSutTarget, switchVersionTarget } from "./navMenu";

describe("menuSelection", () => {
  it("follows the workflow stage instead of the raw path", () => {
    expect(menuSelection("/suts", "")).toBe("sut-list");
    expect(menuSelection("/suts/s1", "")).toBe("sut-overview");
    expect(menuSelection("/suts/s1/model", "")).toBe("model-graph");
    expect(menuSelection("/versions/v1/model", "")).toBe("model-graph");
    expect(menuSelection("/versions/v1/review", "")).toBe("model-review");
    expect(menuSelection("/versions/v1/apis", "")).toBe("model-apis");
    expect(menuSelection("/suts/s1/versions", "")).toBe("sut-requirements");
    expect(menuSelection("/versions/v1", "")).toBe("sut-requirements");
    expect(menuSelection("/versions/v1", "?req=r1")).toBe("sut-requirements");
    expect(menuSelection("/versions/v1", "?tab=strategy")).toBe("sut-strategy");
    expect(menuSelection("/versions/v1/strategy", "")).toBe("sut-strategy");
    expect(menuSelection("/versions/v1/tasks", "")).toBe("sut-tasks");
    expect(menuSelection("/tasks/t1", "")).toBe("sut-tasks");
    expect(menuSelection("/suts/s1/cases", "?version_id=v1")).toBe("sut-cases");
    expect(menuSelection("/cases/c1", "")).toBe("sut-cases");
    expect(menuSelection("/versions/v1", "?tab=cases")).toBe("sut-cases");
  });

  it("highlights the scoped execution entry only when a system is in context", () => {
    expect(menuSelection("/executions", "")).toBe("global-executions");
    expect(menuSelection("/executions", "?sut_id=s1")).toBe("sut-executions");
    expect(menuSelection("/runs/r1", "", "s1")).toBe("sut-executions");
    expect(menuSelection("/runs/r1", "")).toBe("global-executions");
    expect(menuSelection("/defects", "")).toBe("global-defects");
    expect(menuSelection("/defects/d1", "", "s1")).toBe("sut-defects");
    expect(menuSelection("/reports/p1", "?sut_id=s1")).toBe("global-reports");
    expect(menuSelection("/persons", "")).toBe("persons");
    expect(menuSelection("/agent/tools", "")).toBe("agent-tools");
  });
});

describe("system and version switching", () => {
  it("keeps the same section when the system changes", () => {
    expect(switchSutTarget("/versions/v1/model", "", "s2")).toBe("/suts/s2");
    expect(switchSutTarget("/suts/s1/cases", "?version_id=v1", "s2")).toBe("/suts/s2/cases");
    expect(switchSutTarget("/versions/v1/strategy", "", "s2")).toBe("/suts/s2");
    expect(switchSutTarget("/executions", "?version_id=v1", "s2")).toBe("/executions?sut_id=s2");
  });

  it("keeps the version section when the version changes", () => {
    expect(switchVersionTarget("/versions/v1/strategy", "?run=a", "v2")).toBe("/versions/v2/strategy?run=a");
    expect(switchVersionTarget("/versions/v1/model", "?node=n1", "v2")).toBe("/versions/v2/model?node=n1");
    expect(switchVersionTarget("/versions/v1/review", "", "v2")).toBe("/versions/v2/review");
    expect(switchVersionTarget("/suts/s1/apis", "?x=1", "v2")).toBe("/versions/v2/apis?x=1");
    expect(switchVersionTarget("/versions/v1/tasks", "", "v2")).toBe("/versions/v2/tasks");
    expect(switchVersionTarget("/suts/s1/cases", "", "v2", "s1")).toBe("/suts/s1/cases?version_id=v2");
    expect(switchVersionTarget("/executions", "", "v2", "s1")).toBe("/executions?version_id=v2&sut_id=s1");
    expect(switchVersionTarget("/tasks/t1", "", "v2")).toBe("/versions/v2");
  });
});
