import { nothingExecuted, passRateNote, passRateText } from "./ReportsPage";

describe("pass rate note", () => {
  it("never counts skipped / blocked / not run as passed", () => {
    const s = { total: 16, passed: 12, failed: 0, error: 0, blocked: 0, skipped: 4, not_executed: 0, executed: 12, pass_rate: 1 };
    expect(passRateNote(s)).toBe("通过率 = 通过 12 / 已执行 12；4 个已跳过不计为通过");
    expect(passRateNote({ ...s, skipped: 0, executed: undefined })).toBe("通过率 = 通过 12 / 已执行 12");
  });

  it("says how many skipped cases had no automation script", () => {
    const s = { total: 5, passed: 2, failed: 1, error: 0, blocked: 0, skipped: 2, skipped_no_script: 2, not_executed: 0, executed: 3, pass_rate: 0.667 };
    expect(passRateNote(s)).toBe("通过率 = 通过 2 / 已执行 3；2 个已跳过（2 个无自动化脚本）不计为通过");
  });

  it("says nothing was executed when every case lacks a script", () => {
    const s = { total: 2, passed: 0, failed: 0, error: 0, blocked: 0, skipped: 2, skipped_no_script: 2, not_executed: 0, executed: 0, pass_rate: null };
    expect(nothingExecuted(s)).toBe(true);
    expect(passRateText(s)).toBe("未执行");
    expect(passRateNote(s)).toBe("未执行：没有用例真正跑过（2 个无自动化脚本），因此没有通过率");
    // Adding a different skip reason still leaves no execution.
    const mixed = { ...s, skipped: 3, total: 3 };
    expect(nothingExecuted(mixed)).toBe(true);
    expect(passRateText(mixed)).toBe("未执行");
  });

  it.each([
    { total: 0, blocked: 0, skipped: 0, not_executed: 0 },
    { total: 2, blocked: 2, skipped: 0, not_executed: 0 },
    { total: 2, blocked: 0, skipped: 2, not_executed: 0 },
    { total: 2, blocked: 0, skipped: 0, not_executed: 2 },
  ])("never offers a pass rate without executed cases: %j", (counts) => {
    const s = { ...counts, passed: 0, failed: 0, error: 0, executed: 0, pass_rate: null };
    expect(nothingExecuted(s)).toBe(true);
    expect(passRateText(s)).toBe("未执行");
    expect(passRateNote(s)).toContain("未执行：没有用例真正跑过");
    expect(passRateNote(s)).toContain("没有通过率");
  });
});
