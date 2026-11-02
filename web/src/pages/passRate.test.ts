import { passRateNote } from "./ReportsPage";

describe("pass rate note", () => {
  it("never counts skipped / blocked / not run as passed", () => {
    const s = { total: 16, passed: 12, failed: 0, error: 0, blocked: 0, skipped: 4, not_executed: 0, executed: 12, pass_rate: 1 };
    expect(passRateNote(s)).toBe("Pass rate = passed 12 / executed 12; 4 skipped do not count as passed");
    expect(passRateNote({ ...s, skipped: 0, executed: undefined })).toBe("Pass rate = passed 12 / executed 12");
  });
});
