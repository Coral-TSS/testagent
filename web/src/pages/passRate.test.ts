import { passRateNote } from "./ReportsPage";

describe("pass rate note", () => {
  it("never counts skipped / blocked / not run as passed", () => {
    const s = { total: 16, passed: 12, failed: 0, error: 0, blocked: 0, skipped: 4, not_executed: 0, executed: 12, pass_rate: 1 };
    expect(passRateNote(s)).toBe("Pass rate = passed 12 / executed 12; 4 skipped do not count as passed");
    expect(passRateNote({ ...s, skipped: 0, executed: undefined })).toBe("Pass rate = passed 12 / executed 12");
  });

  it("says how many skipped cases had no automation script", () => {
    const s = { total: 5, passed: 2, failed: 1, error: 0, blocked: 0, skipped: 2, skipped_no_script: 2, not_executed: 0, executed: 3, pass_rate: 0.667 };
    expect(passRateNote(s)).toBe("Pass rate = passed 2 / executed 3; 2 skipped (2 without an automation script) do not count as passed");
  });
});
