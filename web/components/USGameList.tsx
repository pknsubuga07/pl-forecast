"use client";

import Link from "next/link";
import { useMemo, useState } from "react";
import type { USGame } from "@/lib/us";
import { ConfidenceBadge, Disagree } from "./ui";
import { Logo } from "./us-ui";

export interface USGameRow extends USGame {
  day: string;
  dayKey: string;
  time: string;
  group: string;      // filter bucket: "Week 9" (NFL) or "Thu, Oct 30" (NBA)
  spreadModel: string;
  spreadMarket: string;
}

export function USGameList({ sport, games, teams }: { sport: string; games: USGameRow[]; teams: { id: string; name: string }[] }) {
  const groups = useMemo(() => [...new Set(games.map((g) => g.group))], [games]);
  const [group, setGroup] = useState<string>(groups[0] ?? "all");
  const [team, setTeam] = useState("all");
  const [onlyDisagree, setOnlyDisagree] = useState(false);
  const shown = games.filter((g) => (group === "all" || g.group === group) && (team === "all" || g.home.id === team || g.away.id === team) && (!onlyDisagree || g.disagreement));
  const days: { key: string; label: string; items: USGameRow[] }[] = [];
  for (const g of shown) {
    const last = days[days.length - 1];
    if (last && last.key === g.dayKey) last.items.push(g);
    else days.push({ key: g.dayKey, label: g.day, items: [g] });
  }
  return (
    <div>
      <div className="mb-4 flex flex-wrap items-center gap-2">
        <div role="group" aria-label={sport === "nfl" ? "Week" : "Day"} className="flex max-w-full overflow-x-auto rounded-lg border border-line bg-surface text-sm">
          {[...groups, "all"].map((g) => (
            <button key={g} type="button" onClick={() => setGroup(g)} aria-pressed={group === g}
              className={`whitespace-nowrap px-3 py-1.5 ${group === g ? "bg-ink text-bg" : "text-ink-2 hover:bg-surface-2"}`}>
              {g === "all" ? "All" : g}
            </button>
          ))}
        </div>
        <label className="sr-only" htmlFor="us-team">Team</label>
        <select id="us-team" value={team} onChange={(e) => setTeam(e.target.value)} className="rounded-lg border border-line bg-surface px-3 py-1.5 text-sm text-ink">
          <option value="all">All teams</option>
          {teams.map((t) => <option key={t.id} value={t.id}>{t.name}</option>)}
        </select>
        <label className="flex items-center gap-2 rounded-lg border border-line bg-surface px-3 py-1.5 text-sm text-ink-2">
          <input type="checkbox" checked={onlyDisagree} onChange={(e) => setOnlyDisagree(e.target.checked)} className="accent-[var(--accent)]" />
          Big model–market gaps
        </label>
        <span className="ml-auto text-xs text-muted">{shown.length} games</span>
      </div>
      {days.length === 0 && <p className="card p-6 text-sm text-muted">No games match these filters.</p>}
      <div className="space-y-6">
        {days.map((d) => (
          <section key={d.key}>
            <h2 className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted">{d.label}</h2>
            <ul className="grid gap-3 md:grid-cols-2">
              {d.items.map((g) => <li key={g.game_id}><GameCard sport={sport} g={g} /></li>)}
            </ul>
          </section>
        ))}
      </div>
    </div>
  );
}

function TeamLine({ t, score, right = false }: { t: USGameRow["home"]; score: number; right?: boolean }) {
  return (
    <div className={`flex min-w-0 items-center gap-2 ${right ? "flex-row-reverse text-right" : ""}`}>
      <Logo src={t.logo} alt={t.short} />
      <div className="min-w-0">
        <div className="truncate font-medium">{t.nickname}</div>
        <div className="text-[11px] text-muted tabular">{t.record.t ? `${t.record.w}-${t.record.l}-${t.record.t}` : `${t.record.w}-${t.record.l}`}</div>
      </div>
      <span className="ml-auto shrink-0 px-1 text-base font-semibold tabular text-ink-2 sm:text-lg" style={right ? { marginLeft: 0, marginRight: "auto" } : undefined}>
        {Math.round(score)}
      </span>
    </div>
  );
}

function GameCard({ sport, g }: { sport: string; g: USGameRow }) {
  return (
    <Link href={`/${sport}/game/${g.game_id}`} className="card block p-4 transition-colors hover:border-[var(--accent)]">
      <div className="mb-3 flex items-center justify-between text-xs text-muted">
        <span className="tabular">{g.time}{g.week ? ` · Week ${g.week}` : ""}{g.playoff ? " · Playoffs" : ""}</span>
        <span className="flex items-center gap-1.5">
          {g.disagreement && <Disagree />}
          <ConfidenceBadge level={g.confidence} short />
        </span>
      </div>
      <div className="grid grid-cols-[1fr_auto_1fr] items-center gap-2">
        <TeamLine t={g.away} score={g.pred_away_score} />
        <span className="text-xs text-muted">@</span>
        <TeamLine t={g.home} score={g.pred_home_score} right />
      </div>
      <div className="mt-3"><WinBarAwayFirst pHome={g.p_home} /></div>
      <div className="mt-2 flex items-center justify-between gap-2 text-xs text-ink-2 tabular">
        <span>Model {g.spreadModel} · O/U {g.pred_total.toFixed(1)}</span>
        <span className="text-right">{g.market_spread_home !== null || g.market_total !== null ? `Market ${g.spreadMarket}${g.market_total ? ` · O/U ${g.market_total}` : ""}` : "No market line yet"}</span>
      </div>
      {g.venue && <div className="mt-1 text-xs text-muted">{g.venue}{g.neutral ? " (neutral site)" : ""}</div>}
    </Link>
  );
}

/** Cards list the away team first (US convention), so the bar mirrors that order. */
function WinBarAwayFirst({ pHome }: { pHome: number }) {
  const a = Math.round((1 - pHome) * 100);
  const h = 100 - a;
  return (
    <div className="flex w-full gap-[2px] overflow-hidden rounded-[5px]" style={{ height: 22 }} role="img" aria-label={`Away ${a}%, home ${h}%`}>
      <div className="flex items-center bg-away pl-2 text-[11px] font-semibold text-white" style={{ width: `${a}%` }}>{a >= 12 ? `${a}%` : ""}</div>
      <div className="flex items-center justify-end bg-home pr-2 text-[11px] font-semibold text-white" style={{ width: `${h}%` }}>{h >= 12 ? `${h}%` : ""}</div>
    </div>
  );
}

