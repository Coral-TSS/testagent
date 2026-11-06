import { nothingExecuted, passRateNote, passRateText } from "./ReportsPage";

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

  it("says nothing was executed when every case lacks a script", () => {
    const s = { total: 2, passed: 0, failed: 0, error: 0, blocked: 0, skipped: 2, skipped_no_script: 2, not_executed: 0, executed: 0, pass_rate: null };
    expect(nothingExecuted(s)).toBe(true);
    expect(passRateText(s)).toBe("Not executed");
    expect(passRateNote(s)).toBe("Not executed: no case ran (2 without an automation script), so there is no pass rate");
    // Adding a different skip reason still leaves no execution.
    const mixed = { ...s, skipped: 3, total: 3 };
    expect(nothingExecuted(mixed)).toBe(true);
    expect(passRateText(mixed)).toBe("Not executed");
  });

  it.each([
    { total: 0, blocked: 0, skipped: 0, not_executed: 0 },
    { total: 2, blocked: 2, skipped: 0, not_executed: 0 },
    { total: 2, blocked: 0, skipped: 2, not_executed: 0 },
    { total: 2, blocked: 0, skipped: 0, not_executed: 2 },
  ])("never offers a pass rate without executed cases: %j", (counts) => {
    const s = { ...counts, passed: 0, failed: 0, error: 0, executed: 0, pass_rate: null };
    expect(nothingExecuted(s)).toBe(true);
    expect(passRateText(s)).toBe("Not executed");
    expect(passRateNote(s)).toContain("Not executed: no case ran");
    expect(passRateNote(s)).toContain("no pass rate");
  });
});
