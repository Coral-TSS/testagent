import { formToBody } from "./CaseForm";

describe("formToBody", () => {
  it("parses test data, trims blanks and drops empty steps", () => {
    const { body, error } = formToBody({
      title: "Amount is 0",
      test_point: "  ",
      steps: [{ action: "Submit" }, { action: " " }],
      test_data: '{"amount": 0}',
      requirement_ids: ["r1"],
    });
    expect(error).toBeUndefined();
    expect(body).toMatchObject({
      title: "Amount is 0",
      test_point: null,
      priority: "P1",
      type_tag: "functional",
      mode: "manual",
      steps: [{ action: "Submit" }],
      test_data: { amount: 0 },
      requirement_ids: ["r1"],
      node_ids: [],
    });
  });

  it("rejects invalid or non-object test data", () => {
    expect(formToBody({ title: "x", test_data: "{bad" }).error).toMatch(/JSON/);
    expect(formToBody({ title: "x", test_data: "[1]" }).error).toMatch(/object/);
  });
});
