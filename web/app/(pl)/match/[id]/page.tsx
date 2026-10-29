import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { MatchSelector } from "@/components/MatchSelector";
import { Card, ConfidenceBadge, Crest, Disagree, ProbBar, ResultPill } from "@/components/ui";
import { getFixtureDetails, getFixtures } from "@/lib/data";
import { fmtDate, fmtKickoff, num, outcomeLabel, pct3, signedPts } from "@/lib/format";
import type { FixtureDetail, Record3, SideContext, TableRow, Underlying } from "@/lib/types";

// A static export needs at least one path; "none" renders a friendly empty state off-season.
export function generateStaticParams() {
  const ids = getFixtures().map((f) => ({ id: f.match_id }));
  return ids.length ? ids : [{ id: "none" }];
}

export async function generateMetadata({ params }: PageProps<"/match/[id]">): Promise<Metadata> {
  const { id } = await params;
  const f = getFixtureDetails()[id];
  return { title: f ? `${f.home.name} v ${f.away.name}` : "Match" };
}

const CONF_HELP = {
  high: "the top outcome is at least 60%, or 30+ points clear of the next",
  medium: "the top outcome is at least 45%, or 15+ points clear of the next",
  low: "the outcomes are close together",
};
const GROUP_LABEL: Record<string, string> = {
  ratings: "Strength ratings (Elo + goals model)",
  recent_form: "Recent form",
  shots: "Shot numbers",
  venue_form: "Home / away form",
  table: "League table",
  rest: "Rest & fixture congestion",
  promoted: "Promoted club",
};
const COMPONENT_LABEL: Record<string, string> = { dc: "Dixon-Coles goals model", gbm: "Gradient boosting", logreg: "Logistic regression", elo: "Elo" };

export default async function MatchPage({ params }: PageProps<"/match/[id]">) {
  const { id } = await params;
  const f = getFixtureDetails()[id];
  if (id === "none" && !f) {
    return <p className="card p-6 text-sm text-muted">No upcoming fixtures right now. <Link href="/" className="underline">Back to fixtures</Link></p>;
  }
  if (!f) notFound();
  const options = getFixtures().map((x) => ({ id: x.match_id, label: `GW${x.gameweek} · ${x.home.short} v ${x.away.short} · ${fmtDate(x.kickoff_utc)}` }));
  const v = pct3(f.p);
  const ctx = f.context;

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <Link href="/" className="text-sm text-ink-2 hover:text-ink">← All fixtures</Link>
        <MatchSelector current={f.match_id} options={options} />
      </div>

      <section className="card overflow-hidden">
        <div className="p-5 sm:p-6">
          <p className="text-center text-xs text-muted">
            Gameweek {f.gameweek} · <time dateTime={f.kickoff_utc}>{fmtKickoff(f.kickoff_utc)} ET</time>
            {f.venue ? ` · ${f.venue}` : ""}
          </p>
          <div className="mt-4 grid grid-cols-[1fr_auto_1fr] items-center gap-3">
            <TeamHead name={f.home.name} team={f.home} row={f.home_table} side="Home" />
            <div className="text-center">
              <div className="text-xs text-muted">xG</div>
              <div className="text-lg font-semibold tabular">{f.xg[0].toFixed(2)} – {f.xg[1].toFixed(2)}</div>
            </div>
            <TeamHead name={f.away.name} team={f.away} row={f.away_table} side="Away" right />
          </div>
          <div className="mt-6">
            <ProbBar p={f.p} height={34} />
            <div className="mt-2 grid grid-cols-3 text-sm tabular">
              <span><b className="text-home">{v[0]}%</b> {f.home.short} win</span>
              <span className="text-center"><b>{v[1]}%</b> draw</span>
              <span className="text-right"><b className="text-away">{v[2]}%</b> {f.away.short} win</span>
            </div>
          </div>
        </div>
        <div className="grid gap-4 border-t border-line bg-surface-2/50 p-5 sm:grid-cols-[auto_1fr] sm:p-6">
          <div className="space-y-2">
            <div className="text-xs text-muted">Predicted outcome</div>
            <div className="text-lg font-semibold">{outcomeLabel(f.predicted, f.home.name, f.away.name)}</div>
            <ConfidenceBadge level={f.confidence} />
            <p className="max-w-[16rem] text-xs text-muted">{f.confidence[0].toUpperCase() + f.confidence.slice(1)}: {CONF_HELP[f.confidence]}.</p>
          </div>
          <div>
            <div className="text-xs text-muted">Why</div>
            <p className="mt-1 text-[15px] leading-relaxed">{f.explanation}</p>
          </div>
        </div>
      </section>

      <div className="grid gap-5 lg:grid-cols-2">
        <Card title="Most likely scorelines">
          <ol className="space-y-1.5">
            {f.top_scores.map((s, i) => (
              <li key={s.score} className="flex items-center gap-3 text-sm">
                <span className="w-4 text-muted">{i + 1}</span>
                <span className="w-10 font-semibold tabular">{s.score}</span>
                <span className="h-2 flex-1 overflow-hidden rounded-full bg-surface-2">
                  <span className="block h-full rounded-full bg-accent" style={{ width: `${(s.p / f.top_scores[0].p) * 100}%` }} />
                </span>
                <span className="w-12 text-right tabular text-ink-2">{(s.p * 100).toFixed(1)}%</span>
              </li>
            ))}
          </ol>
          <ScoreGrid grid={f.score_grid} home={f.home.short} away={f.away.short} />
          <p className="mt-3 text-xs text-muted">
            From the Dixon-Coles goals model, rescaled so the home / draw / away totals match the final prediction.
            Expected goals: {f.home.short} {f.xg[0].toFixed(2)}, {f.away.short} {f.xg[1].toFixed(2)}.
          </p>
        </Card>

        <Card title="Model vs bookmakers" action={f.disagreement ? <Disagree /> : undefined}>
          {f.market ? (
            <>
              <table className="w-full text-sm tabular">
                <thead>
                  <tr className="text-left text-xs text-muted">
                    <th className="pb-2 font-normal">Outcome</th>
                    <th className="pb-2 text-right font-normal">Model</th>
                    <th className="pb-2 text-right font-normal">Market</th>
                    <th className="pb-2 text-right font-normal">Gap</th>
                  </tr>
                </thead>
                <tbody>
                  {[`${f.home.short} win`, "Draw", `${f.away.short} win`].map((label, i) => {
                    const gap = f.p[i] - f.market!.p[i];
                    const big = Math.abs(gap) >= 0.1;
                    return (
                      <tr key={label} className="border-t border-line">
                        <td className="py-2">{label}</td>
                        <td className="py-2 text-right font-medium">{pct3(f.p)[i]}%</td>
                        <td className="py-2 text-right">{pct3(f.market!.p)[i]}%</td>
                        <td className={`py-2 text-right ${big ? "font-semibold text-warn" : "text-ink-2"}`}>{signedPts(gap)}{big ? " ◆" : ""}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
              <div className="mt-3">
                <div className="mb-1 text-xs text-muted">Market</div>
                <ProbBar p={f.market.p} height={14} labels={false} />
              </div>
              <p className="mt-3 text-xs text-muted">
                {f.market.label}: decimal odds {f.market.odds.map((o) => o.toFixed(2)).join(" / ")}, bookmaker margin{" "}
                {(f.market.overround * 100).toFixed(1)}% removed proportionally. ◆ marks gaps of 10+ points. Bookmakers have
                historically been more accurate than this model (see Performance), so a big gap is more often the model
                missing something (injuries, team news) than a mispriced market.
              </p>
            </>
          ) : (
            <p className="text-sm text-muted">
              Odds for this fixture are not available yet. football-data.co.uk usually publishes them a few days before the
              round; DraftKings odds via ESPN appear about a week ahead.
            </p>
          )}
        </Card>
      </div>

      <div className="grid gap-5 lg:grid-cols-2">
        <SideCard title="Recent form" f={f} render={(c, name) => <FormBlock c={c} name={name} />} />
        <Card title="League position">
          <TableCompare home={f.home_table} away={f.away_table} hn={f.home.short} an={f.away.short} />
        </Card>
      </div>

      <div className="grid gap-5 lg:grid-cols-2">
        <Card title={`${f.home.short} at home · ${f.away.short} away`}>
          <VenueTable home={ctx.home} away={ctx.away} hn={f.home.short} an={f.away.short} />
        </Card>
        <Card title="Underlying numbers (this season, per game)">
          <UnderlyingTable h={ctx.home.underlying} a={ctx.away.underlying} hn={f.home.short} an={f.away.short} />
        </Card>
      </div>

      <div className="grid gap-5 lg:grid-cols-2">
        <Card title="Rest since last match (all competitions)">
          <div className="grid gap-3 sm:grid-cols-2">
            {[["home", f.home.name, ctx.home], ["away", f.away.name, ctx.away]].map(([k, name, c]) => {
              const lm = (c as SideContext).last_match;
              return (
                <div key={k as string} className="rounded-lg bg-surface-2 p-3">
                  <div className="text-xs text-muted">{name as string}</div>
                  {lm ? (
                    <>
                      <div className="text-2xl font-semibold tabular">{lm.days.toFixed(1)} <span className="text-sm font-normal text-ink-2">days</span></div>
                      <div className="text-xs text-ink-2">{lm.competition} v {lm.opponent}, {fmtDate(lm.kickoff_utc)}</div>
                    </>
                  ) : (
                    <div className="text-sm text-muted">No earlier match this season</div>
                  )}
                </div>
              );
            })}
          </div>
          <p className="mt-3 text-xs text-muted">Includes domestic cups and European games from ESPN&apos;s schedule data.</p>
        </Card>
        <Card title={`Head to head (last ${ctx.h2h.meetings.length})`}>
          <H2H f={f} />
        </Card>
      </div>

      <div className="grid gap-5 lg:grid-cols-2">
        <Card title="What moves this prediction">
          <Factors f={f} />
        </Card>
        <Card title="Model components">
          <ul className="space-y-3">
            {Object.entries(f.components).map(([k, p]) => (
              <li key={k}>
                <div className="mb-1 flex justify-between text-xs">
                  <span className="text-ink-2">{COMPONENT_LABEL[k] ?? k}</span>
                  <span className="text-muted">weight {((f.weights[k] ?? 0) * 100).toFixed(0)}%</span>
                </div>
                <ProbBar p={p} height={16} compact />
              </li>
            ))}
          </ul>
          <p className="mt-3 text-xs text-muted">
            The final prediction is the weighted average shown. Weights were chosen on the 2016-17 to 2020-21 validation
            seasons. Model version {f.model_version}.
          </p>
        </Card>
      </div>
    </div>
  );
}

function TeamHead({ name, team, row, side, right = false }: { name: string; team: FixtureDetail["home"]; row: TableRow | null; side: string; right?: boolean }) {
  return (
    <Link href={`/teams/${team.id}`} className={`flex min-w-0 flex-col items-center gap-2 text-center hover:opacity-80`}>
      <Crest team={team} size={56} />
      <div className="min-w-0">
        <div className="truncate text-base font-semibold sm:text-lg">{name}</div>
        <div className="text-xs text-muted">
          {side}
          {row ? ` · ${ordinal(row.position)} · ${row.points} pts` : ""}
        </div>
      </div>
      <span className="sr-only">{right ? "away team" : "home team"}</span>
    </Link>
  );
}

function ordinal(n: number) {
  const s = n % 100 >= 11 && n % 100 <= 13 ? "th" : ({ 1: "st", 2: "nd", 3: "rd" } as Record<number, string>)[n % 10] ?? "th";
  return `${n}${s}`;
}

function ScoreGrid({ grid, home, away }: { grid: number[][]; home: string; away: string }) {
  const max = Math.max(...grid.flat());
  return (
    <div className="mt-4 overflow-x-auto">
      <table className="mx-auto text-[11px] tabular" aria-label="Score probability grid">
        <thead>
          <tr>
            <th className="p-1 text-left font-normal text-muted">{home} ↓ {away} →</th>
            {grid[0].map((_, j) => <th key={j} className="w-9 p-1 font-medium text-ink-2">{j}</th>)}
          </tr>
        </thead>
        <tbody>
          {grid.map((row, i) => (
            <tr key={i}>
              <th className="p-1 text-right font-medium text-ink-2">{i}</th>
              {row.map((p, j) => {
                const t = p / max;
                return (
                  <td
                    key={j}
                    title={`${home} ${i}–${j} ${away}: ${(p * 100).toFixed(1)}%`}
                    className="h-8 w-9 rounded-[4px] text-center"
                    style={{
                      background: `color-mix(in oklab, var(--home) ${Math.round(t * 85)}%, var(--surface-2))`,
                      color: t > 0.55 ? "white" : "var(--text-2)",
                      border: "2px solid var(--surface)",
                    }}
                  >
                    {p >= 0.01 ? (p * 100).toFixed(0) : ""}
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function SideCard({ title, f, render }: { title: string; f: FixtureDetail; render: (c: SideContext, name: string) => React.ReactNode }) {
  return (
    <Card title={title}>
      <div className="space-y-4">
        {render(f.context.home, f.home.name)}
        {render(f.context.away, f.away.name)}
      </div>
    </Card>
  );
}

function FormBlock({ c, name }: { c: SideContext; name: string }) {
  return (
    <div>
      <div className="mb-1.5 flex items-baseline justify-between gap-2">
        <span className="text-sm font-medium">{name}</span>
        <span className="text-xs text-muted tabular">Scored {c.form_goals_for} · conceded {c.form_goals_against} (last {c.form.length})</span>
      </div>
      <div className="flex flex-wrap gap-1.5">
        {c.form.map((m) => (
          <div key={m.date} className="flex items-center gap-1.5 rounded-lg bg-surface-2 py-1 pl-1 pr-2 text-xs">
            <ResultPill r={m.result} title={`${m.venue === "H" ? "v" : "at"} ${m.opponent}, ${fmtDate(m.date)}`} />
            <span className="tabular">{m.gf}–{m.ga}</span>
            <span className="text-muted">{m.venue === "H" ? "v" : "@"} {m.opponent_short}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

function TableCompare({ home, away, hn, an }: { home: TableRow | null; away: TableRow | null; hn: string; an: string }) {
  if (!home || !away) return <p className="text-sm text-muted">Table not available yet.</p>;
  const rows: [string, (r: TableRow) => string][] = [
    ["Position", (r) => ordinal(r.position)],
    ["Points", (r) => `${r.points}${r.deduction ? ` (${r.deduction})` : ""}`],
    ["Played", (r) => String(r.played)],
    ["W-D-L", (r) => `${r.won}-${r.drawn}-${r.lost}`],
    ["Goal difference", (r) => `${r.gd > 0 ? "+" : ""}${r.gd}`],
    ["Points per game", (r) => num(r.ppg, 2)],
  ];
  return (
    <table className="w-full text-sm tabular">
      <thead>
        <tr className="text-xs text-muted">
          <th className="pb-2 text-left font-normal"></th>
          <th className="pb-2 text-right font-medium text-home">{hn}</th>
          <th className="pb-2 text-right font-medium text-away">{an}</th>
        </tr>
      </thead>
      <tbody>
        {rows.map(([label, fn]) => (
          <tr key={label} className="border-t border-line">
            <td className="py-1.5 text-ink-2">{label}</td>
            <td className="py-1.5 text-right font-medium">{fn(home)}</td>
            <td className="py-1.5 text-right font-medium">{fn(away)}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function rec(r: Record3) {
  return r.p ? `${r.w}-${r.d}-${r.l}` : "–";
}

function VenueTable({ home, away, hn, an }: { home: SideContext; away: SideContext; hn: string; an: string }) {
  const rows = [
    { label: `${hn} at home`, cls: "text-home", s: home.venue_record.this_season, l: home.venue_record.last_season },
    { label: `${an} away`, cls: "text-away", s: away.venue_record.this_season, l: away.venue_record.last_season },
  ];
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[22rem] text-sm tabular">
        <thead>
          <tr className="text-xs text-muted">
            <th className="pb-2 text-left font-normal"></th>
            <th className="pb-2 text-right font-normal">This season W-D-L</th>
            <th className="pb-2 text-right font-normal">GF–GA</th>
            <th className="pb-2 text-right font-normal">PPG</th>
            <th className="pb-2 text-right font-normal">Last season</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.label} className="border-t border-line">
              <td className={`py-2 font-medium ${r.cls}`}>{r.label}</td>
              <td className="py-2 text-right">{rec(r.s)}</td>
              <td className="py-2 text-right">{r.s.p ? `${r.s.gf}–${r.s.ga}` : "–"}</td>
              <td className="py-2 text-right font-medium">{num(r.s.ppg, 2)}</td>
              <td className="py-2 text-right text-ink-2">
                {rec(r.l)} · {num(r.l.ppg, 2)} ppg
                {r.l.division === "Championship" && <span className="block text-[11px] text-muted">in the Championship</span>}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function UnderlyingTable({ h, a, hn, an }: { h: Underlying; a: Underlying; hn: string; an: string }) {
  const rows: [string, keyof Underlying, number][] = [
    ["xG for", "xg_for_pg", 2],
    ["xG against", "xg_against_pg", 2],
    ["Goals for", "goals_for_pg", 2],
    ["Goals against", "goals_against_pg", 2],
    ["Shots for", "shots_for_pg", 1],
    ["Shots against", "shots_against_pg", 1],
    ["On target for", "sot_for_pg", 1],
    ["On target against", "sot_against_pg", 1],
    ["Clean sheets (total)", "clean_sheets", 0],
  ];
  return (
    <>
      <table className="w-full text-sm tabular">
        <thead>
          <tr className="text-xs text-muted">
            <th className="pb-2 text-left font-normal"></th>
            <th className="pb-2 text-right font-medium text-home">{hn}</th>
            <th className="pb-2 text-right font-medium text-away">{an}</th>
          </tr>
        </thead>
        <tbody>
          {rows.map(([label, key, d]) => (
            <tr key={label} className="border-t border-line">
              <td className="py-1.5 text-ink-2">{label}</td>
              <td className="py-1.5 text-right">{num(h[key] as number | null, d)}</td>
              <td className="py-1.5 text-right">{num(a[key] as number | null, d)}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="mt-2 text-xs text-muted">
        Premier League matches only. xG from football-data.co.uk ({h.xg_matches ?? 0} and {a.xg_matches ?? 0} matches with xG).
      </p>
    </>
  );
}

function H2H({ f }: { f: FixtureDetail }) {
  const h = f.context.h2h;
  if (!h.meetings.length) return <p className="text-sm text-muted">These clubs have not met in the league since 2004-05.</p>;
  return (
    <>
      <div className="mb-3 flex gap-4 text-sm tabular">
        <span><b className="text-home">{h.home_wins}</b> {f.home.short} wins</span>
        <span><b>{h.draws}</b> draws</span>
        <span><b className="text-away">{h.away_wins}</b> {f.away.short} wins</span>
      </div>
      <ul className="divide-y divide-line text-sm">
        {h.meetings.map((m) => (
          <li key={m.date} className="flex items-center gap-2 py-1.5">
            <ResultPill r={m.result_for_home_team} title={`Result for ${f.home.name}`} />
            <span className="w-24 shrink-0 text-xs text-muted tabular">{fmtDate(m.date)}</span>
            <span className="min-w-0 flex-1 truncate">
              {m.home} <b className="tabular">{m.home_goals}–{m.away_goals}</b> {m.away}
            </span>
            {m.division !== "Premier League" && <span className="text-[11px] text-muted">Champ.</span>}
          </li>
        ))}
      </ul>
      <p className="mt-2 text-xs text-muted">W/D/L from {f.home.name}&apos;s point of view. League meetings only.</p>
    </>
  );
}

function Factors({ f }: { f: FixtureDetail }) {
  const items = f.factors.filter((x) => Math.abs(x.home_minus_away) >= 0.002).slice(0, 6);
  const max = Math.max(0.05, ...items.map((x) => Math.abs(x.home_minus_away)));
  return (
    <>
      <div className="mb-2 flex justify-between text-[11px] text-muted">
        <span className="text-away">← favours {f.away.short}</span>
        <span className="text-home">favours {f.home.short} →</span>
      </div>
      <ul className="space-y-2.5">
        {items.map((x) => {
          const w = (Math.abs(x.home_minus_away) / max) * 50;
          const home = x.home_minus_away > 0;
          return (
            <li key={x.group} title={x.text}>
              <div className="mb-1 flex justify-between text-xs">
                <span className="text-ink-2">{GROUP_LABEL[x.group] ?? x.group}</span>
                <span className="tabular text-muted">{signedPts(x.home_minus_away)}</span>
              </div>
              <div className="relative h-2.5 rounded-full bg-surface-2">
                <span className="absolute inset-y-0 left-1/2 w-px bg-line" />
                <span
                  className={`absolute inset-y-0 rounded-[4px] ${home ? "bg-home" : "bg-away"}`}
                  style={home ? { left: "50%", width: `${w}%` } : { right: "50%", width: `${w}%` }}
                />
              </div>
            </li>
          );
        })}
      </ul>
      <p className="mt-3 text-xs text-muted">
        Each bar shows how the gap between home-win and away-win probability changes when the two teams are made equal on
        that group of inputs. It explains the model, not football causality.
      </p>
    </>
  );
}
