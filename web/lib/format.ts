import type { Outcome } from "./types";

export const TZ = "America/New_York";

const dateTime = new Intl.DateTimeFormat("en-US", {
  timeZone: TZ, weekday: "short", month: "short", day: "numeric", hour: "numeric", minute: "2-digit",
});
const dateOnly = new Intl.DateTimeFormat("en-US", { timeZone: TZ, month: "short", day: "numeric", year: "numeric" });
const dayHeading = new Intl.DateTimeFormat("en-US", { timeZone: TZ, weekday: "long", month: "long", day: "numeric" });
const timeOnly = new Intl.DateTimeFormat("en-US", { timeZone: TZ, hour: "numeric", minute: "2-digit", timeZoneName: "short" });
const dayKeyFmt = new Intl.DateTimeFormat("en-CA", { timeZone: TZ, year: "numeric", month: "2-digit", day: "2-digit" });

export const fmtKickoff = (iso: string) => dateTime.format(new Date(iso));
export const fmtDate = (iso: string) => dateOnly.format(new Date(iso));
export const fmtDay = (iso: string) => dayHeading.format(new Date(iso));
export const fmtTime = (iso: string) => timeOnly.format(new Date(iso));
export const dayKey = (iso: string) => dayKeyFmt.format(new Date(iso));
export const fmtUpdated = (iso: string) =>
  new Intl.DateTimeFormat("en-US", {
    timeZone: TZ, month: "short", day: "numeric", hour: "numeric", minute: "2-digit", timeZoneName: "short",
  }).format(new Date(iso));

/** Percentages that always add up to 100 (largest-remainder rounding). */
export function pct3(p: readonly number[]): number[] {
  const total = p.reduce((a, b) => a + b, 0);
  const raw = p.map((x) => (x / total) * 100);
  const floor = raw.map(Math.floor);
  let left = 100 - floor.reduce((a, b) => a + b, 0);
  const order = raw.map((x, i) => [x - Math.floor(x), i] as const).sort((a, b) => b[0] - a[0]);
  for (const [, i] of order) {
    if (left <= 0) break;
    floor[i] += 1;
    left -= 1;
  }
  return floor;
}

export const pct = (x: number, digits = 0) => `${(x * 100).toFixed(digits)}%`;
export const signedPts = (x: number) => `${x > 0 ? "+" : ""}${(x * 100).toFixed(0)} pts`;

export function outcomeLabel(o: Outcome, home: string, away: string): string {
  return o === "H" ? `${home} win` : o === "A" ? `${away} win` : "Draw";
}

export const num = (x: number | null | undefined, digits = 1) =>
  x === null || x === undefined || Number.isNaN(x) ? "–" : x.toFixed(digits);
