import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { EloChart, FormChart } from "@/components/charts";
import { Card, Crest, ProbBar, ResultPill, Stat } from "@/components/ui";
import { getFixtureDetails, getTeams } from "@/lib/data";
import { fmtKickoff, num } from "@/lib/format";

export function generateStaticParams() {
  return Object.keys(getTeams()).map((id) => ({ id }));
}

export async function generateMetadata({ params }: PageProps<"/teams/[id]">): Promise<Metadata> {
  const { id } = await params;
  return { title: getTeams()[id]?.name ?? "Team" };
}

export default async function TeamPage({ params }: PageProps<"/teams/[id]">) {
  const { id } = await params;
  const t = getTeams()[id];
  if (!t) notFound();
  const details = getFixtureDetails();
  const upcoming = t.upcoming.map((m) => details[m]).filter(Boolean);
  const champ = t.elo_history.some((e) => e.div === "E1");
  const u = t.underlying;

  return (
    <div className="space-y-5">
      <div className="flex items-center gap-4">
        <Crest team={t} size={64} />
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">{t.name}</h1>
          <p className="text-sm text-ink-2">{t.stadium ?? ""}</p>
        </div>
      </div>

      <div className="grid gap-3 sm:grid-cols-4">
        <div className="card p-4"><Stat label="Position" value={t.table ? t.table.position : "–"} sub={t.table ? `${t.table.points} pts · GD ${t.table.gd > 0 ? "+" : ""}${t.table.gd}` : undefined} /></div>
        <div className="card p-4"><Stat label="Elo rating" value={t.elo_now.toFixed(0)} /></div>
        <div className="card p-4"><Stat label="Home W-D-L" value={`${t.home_record.w}-${t.home_record.d}-${t.home_record.l}`} sub={`${num(t.home_record.ppg, 2)} ppg`} /></div>
        <div className="card p-4"><Stat label="Away W-D-L" value={`${t.away_record.w}-${t.away_record.d}-${t.away_record.l}`} sub={`${num(t.away_record.ppg, 2)} ppg`} /></div>
      </div>

      <div className="grid gap-5 lg:grid-cols-2">
        <Card title="Elo rating over time">
          <EloChart data={t.elo_history} />
          <p className="mt-2 text-xs text-muted">
            Last four seasons{champ ? ", including Championship matches (one shared rating scale)" : ""}.
          </p>
        </Card>
        <Card title="Form trend (rolling 5-match points per game)">
          <FormChart data={t.form_trend} />
          <div className="mt-2 flex flex-wrap gap-1">
            {t.form_trend.slice(-10).map((f) => (
              <ResultPill key={f.date} r={f.result} title={`${f.date} ${f.venue === "H" ? "v" : "@"} ${f.opponent} ${f.gf}–${f.ga}`} />
            ))}
          </div>
        </Card>
      </div>

      <div className="grid gap-5 lg:grid-cols-2">
        <Card title="Upcoming fixtures">
          {upcoming.length ? (
            <ul className="space-y-3">
              {upcoming.map((f) => (
                <li key={f.match_id}>
                  <Link href={`/match/${f.match_id}`} className="block rounded-lg p-2 hover:bg-surface-2">
                    <div className="mb-1.5 flex items-center justify-between text-sm">
                      <span className="font-medium">{f.home.name} v {f.away.name}</span>
                      <span className="text-xs text-muted">{fmtKickoff(f.kickoff_utc)}</span>
                    </div>
                    <ProbBar p={f.p} height={16} compact />
                  </Link>
                </li>
              ))}
            </ul>
          ) : (
            <p className="text-sm text-muted">No fixtures in the next few gameweeks.</p>
          )}
        </Card>
        <Card title="This season per game">
          <dl className="grid grid-cols-2 gap-3 text-sm tabular">
            {[
              ["xG for", num(u.xg_for_pg, 2)], ["xG against", num(u.xg_against_pg, 2)],
              ["Goals for", num(u.goals_for_pg, 2)], ["Goals against", num(u.goals_against_pg, 2)],
              ["Shots for", num(u.shots_for_pg)], ["Shots against", num(u.shots_against_pg)],
              ["On target for", num(u.sot_for_pg)], ["On target against", num(u.sot_against_pg)],
              ["Clean sheets", String(u.clean_sheets ?? "–")],
            ].map(([k, v]) => (
              <div key={k} className="rounded-lg bg-surface-2 px-3 py-2">
                <dt className="text-xs text-muted">{k}</dt>
                <dd className="font-semibold">{v}</dd>
              </div>
            ))}
          </dl>
        </Card>
      </div>
    </div>
  );
}
