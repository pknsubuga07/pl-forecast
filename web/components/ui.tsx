import type { ReactNode } from "react";
import { pct3 } from "@/lib/format";
import type { Probs, Team } from "@/lib/types";

export function Crest({ team, size = 28 }: { team: Pick<Team, "crest" | "short" | "name">; size?: number }) {
  if (!team.crest) {
    return (
      <span
        aria-hidden
        style={{ width: size, height: size, fontSize: size * 0.34 }}
        className="grid shrink-0 place-items-center rounded-full bg-surface-2 font-semibold text-ink-2"
      >
        {team.short}
      </span>
    );
  }
  // eslint-disable-next-line @next/next/no-img-element
  return <img src={team.crest} alt="" width={size} height={size} loading="lazy" className="shrink-0 object-contain" style={{ width: size, height: size }} />;
}

const SEG = ["bg-home text-white", "bg-draw text-[#1b1b1a] dark:text-white", "bg-away text-white"];

/** Home / draw / away bar. Segments are separated by a 2px surface gap and always labelled. */
export function ProbBar({ p, labels = true, height = 22, compact = false }: { p: Probs; labels?: boolean; height?: number; compact?: boolean }) {
  const v = pct3(p);
  const names = ["Home", "Draw", "Away"];
  return (
    <div
      className="flex w-full gap-[2px] overflow-hidden rounded-[5px]"
      style={{ height }}
      role="img"
      aria-label={`Home ${v[0]}%, draw ${v[1]}%, away ${v[2]}%`}
    >
      {v.map((x, i) => (
        <div
          key={i}
          className={`${SEG[i]} flex min-w-0 items-center ${i === 0 ? "justify-start pl-2" : i === 2 ? "justify-end pr-2" : "justify-center"} text-[11px] font-semibold`}
          style={{ width: `${x}%` }}
          title={`${names[i]} ${x}%`}
        >
          {labels && x >= (compact ? 14 : 9) ? `${x}%` : ""}
        </div>
      ))}
    </div>
  );
}

export function OutcomeLegend() {
  return (
    <div className="flex items-center gap-3 text-xs text-ink-2">
      {[["bg-home", "Home win"], ["bg-draw", "Draw"], ["bg-away", "Away win"]].map(([c, l]) => (
        <span key={l} className="flex items-center gap-1.5">
          <span className={`h-2.5 w-2.5 rounded-[3px] ${c}`} />
          {l}
        </span>
      ))}
    </div>
  );
}

const CONF = {
  high: { label: "High confidence", cls: "border-win/40 text-win", bars: 3 },
  medium: { label: "Medium confidence", cls: "border-warn/40 text-warn", bars: 2 },
  low: { label: "Low confidence", cls: "border-line text-muted", bars: 1 },
};

export function ConfidenceBadge({ level, short = false }: { level: "high" | "medium" | "low"; short?: boolean }) {
  const c = CONF[level];
  return (
    <span className={`inline-flex items-center gap-1.5 rounded-full border px-2 py-0.5 text-[11px] font-medium ${c.cls}`}>
      <span aria-hidden className="flex items-end gap-[2px]">
        {[1, 2, 3].map((b) => (
          <span key={b} className={`w-[3px] rounded-sm ${b <= c.bars ? "bg-current" : "bg-line"}`} style={{ height: 3 + b * 3 }} />
        ))}
      </span>
      {short ? level[0].toUpperCase() + level.slice(1) : c.label}
    </span>
  );
}

const RES = { W: "bg-win", D: "bg-draw", L: "bg-loss" };

export function ResultPill({ r, title }: { r: "W" | "D" | "L"; title?: string }) {
  return (
    <span title={title} className={`grid h-6 w-6 place-items-center rounded-md text-[11px] font-bold text-white ${RES[r]}`}>
      {r}
    </span>
  );
}

export function Card({ title, children, className = "", action }: { title?: ReactNode; children: ReactNode; className?: string; action?: ReactNode }) {
  return (
    <section className={`card p-4 sm:p-5 ${className}`}>
      {title && (
        <div className="mb-3 flex items-center justify-between gap-2">
          <h2 className="text-sm font-semibold tracking-tight">{title}</h2>
          {action}
        </div>
      )}
      {children}
    </section>
  );
}

export function Stat({ label, value, sub }: { label: string; value: ReactNode; sub?: ReactNode }) {
  return (
    <div>
      <div className="text-xs text-muted">{label}</div>
      <div className="text-xl font-semibold tabular">{value}</div>
      {sub && <div className="text-xs text-ink-2">{sub}</div>}
    </div>
  );
}

export function Disagree() {
  return (
    <span className="inline-flex items-center gap-1 rounded-full bg-warn/15 px-2 py-0.5 text-[11px] font-medium text-warn">
      <span aria-hidden>◆</span> Model vs market
    </span>
  );
}
