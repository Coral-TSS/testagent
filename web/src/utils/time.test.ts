import { fmtTime } from "./time";

describe("fmtTime", () => {
  it("formats in an explicit IANA zone", () => {
    expect(fmtTime("2026-10-31T01:00:00Z", { tz: "Asia/Shanghai" })).toBe("2026-10-31 09:00");
    expect(fmtTime("2026-10-31T16:30:05Z", { tz: "Asia/Shanghai", seconds: true })).toBe("2026-11-01 00:30:05");
    expect(fmtTime("2026-10-31T01:00:00+00:00", { tz: "UTC" })).toBe("2026-10-31 01:00");
    expect(fmtTime(null)).toBe("-");
  });
});
