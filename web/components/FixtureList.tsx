"use client";

import Link from "next/link";
import { useMemo, useState } from "react";
import { pct3 } from "@/lib/format";
import type { FixtureSummary } from "@/lib/types";
import { ConfidenceBadge, Crest, Disagree, ProbBar } from "./ui";

export interface FixtureRow extends FixtureSummary {
  day: string;
  dayKey: string;
  time: string;
}

export function FixtureList({ fixtures, teams }: { fixtures: FixtureRow[]; teams: { id: string; name: string }[] }) {
  const gameweeks = useMemo(() => [...new Set(fixtures.map((f) => f.gameweek))].sort((a, b) => a - b), [fixtures]);
  const [gw, setGw] = useState<number | "all">(gameweeks[0] ?? "all");
  const [team, setTeam] = useState("all");
  const [onlyDisagree, setOnlyDisagree] = useState(false);

  const shown = fixtures.filter(
    (f) =>
      (gw === "all" || f.gameweek === gw) &&
      (team === "all" || f.home.id === team || f.away.id === team) &&
      (!onlyDisagree || f.disagreement),
  );
  const days: { key: string; label: string; items: FixtureRow[] }[] = [];
  for (const f of shown) {
    const last = days[days.length - 1];
    if (last && last.key === `${f.gameweek}-${f.dayKey}`) last.items.push(f);
    else days.push({ key: `${f.gameweek}-${f.dayKey}`, label: f.day, items: [f] });
  }

  return (
    <div>
      <div className="mb-4 flex flex-wrap items-center gap-2">
        <div role="group" aria-label="Gameweek" className="flex overflow-hidden rounded-lg border border-line bg-surface text-sm">
          {gameweeks.map((g) => (
            <button
              key={g}
              type="button"
              onClick={() => setGw(g)}
              aria-pressed={gw === g}
              className={`px-3 py-1.5 ${gw === g ? "bg-ink text-bg" : "text-ink-2 hover:bg-surface-2"}`}
            >
              GW{g}
            </button>
          ))}
          <button
            type="button"
            onClick={() => setGw("all")}
            aria-pressed={gw === "all"}
            className={`px-3 py-1.5 ${gw === "all" ? "bg-ink text-bg" : "text-ink-2 hover:bg-surface-2"}`}
          >
            All
          </button>
        </div>
        <label className="sr-only" htmlFor="team-filter">Team</label>
        <select
          id="team-filter"
          value={team}
          onChange={(e) => setTeam(e.target.value)}
          className="rounded-lg border border-line bg-surface px-3 py-1.5 text-sm text-ink"
        >
          <option value="all">All teams</option>
          {teams.map((t) => (
            <option key={t.id} value={t.id}>{t.name}</option>
          ))}
        </select>
        <label className="flex items-center gap-2 rounded-lg border border-line bg-surface px-3 py-1.5 text-sm text-ink-2">
          <input type="checkbox" checked={onlyDisagree} onChange={(e) => setOnlyDisagree(e.target.checked)} className="accent-[var(--accent)]" />
          Big model–market gaps
        </label>
        <span className="ml-auto text-xs text-muted">{shown.length} fixtures</span>
      </div>

      {days.length === 0 && <p className="card p-6 text-sm text-muted">No fixtures match these filters.</p>}

      <div className="space-y-6">
        {days.map((d) => (
          <section key={d.key}>
            <h2 className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted">{d.label}</h2>
            <ul className="grid gap-3 md:grid-cols-2">
              {d.items.map((f) => (
                <li key={f.match_id}>
                  <FixtureCard f={f} />
                </li>
              ))}
            </ul>
          </section>
        ))}
      </div>
    </div>
  );
}

function FixtureCard({ f }: { f: FixtureRow }) {
  const v = pct3(f.p);
  const m = f.market_p ? pct3(f.market_p) : null;
  return (
    <Link
      href={`/match/${f.match_id}`}
      className="card block p-4 transition-colors hover:border-[var(--accent)] focus-visible:outline-2 focus-visible:outline-[var(--accent)]"
    >
      <div className="mb-3 flex items-center justify-between text-xs text-muted">
        <span className="tabular">{f.time} · GW{f.gameweek}</span>
        <span className="flex items-center gap-1.5">
          {f.disagreement && <Disagree />}
          <ConfidenceBadge level={f.confidence} short />
        </span>
      </div>
      <div className="grid grid-cols-[1fr_auto_1fr] items-center gap-2">
        <div className="flex min-w-0 items-center gap-2">
          <Crest team={f.home} />
          <span className="truncate font-medium">{f.home.name}</span>
        </div>
        <span className="text-xs text-muted">vs</span>
        <div className="flex min-w-0 items-center justify-end gap-2">
          <span className="truncate text-right font-medium">{f.away.name}</span>
          <Crest team={f.away} />
        </div>
      </div>
      <div className="mt-3">
        <ProbBar p={f.p} compact />
      </div>
      <div className="mt-2 flex items-center justify-between text-xs text-ink-2 tabular">
        <span>Model {v[0]} / {v[1]} / {v[2]}</span>
        <span>{m ? `Market ${m[0]} / ${m[1]} / ${m[2]}` : "Market odds not yet available"}</span>
      </div>
      <div className="mt-1 text-xs text-muted">
        Most likely score {f.top_score.score} · xG {f.xg[0].toFixed(1)}–{f.xg[1].toFixed(1)}
        {f.venue ? ` · ${f.venue}` : ""}
      </div>
    </Link>
  );
}
