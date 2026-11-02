import dayjs from "dayjs";

const pad = (n: string) => n.padStart(2, "0");

/** Formats an ISO timestamp as local wall-clock time ("YYYY-MM-DD HH:mm[:ss]").
 *  Without `tz` the browser's zone is used; with `tz` (IANA name) that zone is used. */
export function fmtTime(value: string | null | undefined, opts: { seconds?: boolean; tz?: string } = {}): string {
  if (!value) return "-";
  if (!opts.tz) return dayjs(value).format(opts.seconds ? "YYYY-MM-DD HH:mm:ss" : "YYYY-MM-DD HH:mm");
  const parts = Object.fromEntries(
    new Intl.DateTimeFormat("en-CA", {
      timeZone: opts.tz,
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
      hourCycle: "h23",
    })
      .formatToParts(new Date(value))
      .map((p) => [p.type, p.value]),
  );
  const base = `${parts.year}-${pad(parts.month)}-${pad(parts.day)} ${pad(parts.hour)}:${pad(parts.minute)}`;
  return opts.seconds ? `${base}:${pad(parts.second)}` : base;
}

export const browserTimezone = () => Intl.DateTimeFormat().resolvedOptions().timeZone;
