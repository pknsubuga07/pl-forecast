import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { EloChart, MarginChart } from "@/components/charts";
import { Card, Stat } from "@/components/ui";
import { Logo, WLPill } from "@/components/us-ui";
import { fmtKickoff } from "@/lib/format";
import { isSport, rec, SPORTS, usDetails, usTeams, type Sport } from "@/lib/us";

export async function generateStaticParams({ params }: { params: { sport: string } }) {
  const sports = params?.sport ? [params.sport as Sport] : SPORTS;
  return sports.flatMap((s) => {
    const ids = Object.keys(usTeams(s));
    return (ids.length ? ids : ["none"]).map((id) => ({ sport: s, id }));
  });
}

export async function generateMetadata({ params }: PageProps<"/[sport]/teams/[id]">): Promise<Metadata> {
  const { sport, id } = await params;
  return { title: isSport(sport) ? usTeams(sport)[id]?.name ?? "Team" : "Team" };
}

export default async function USTeamPage({ params }: PageProps<"/[sport]/teams/[id]">) {
  const { sport, id } = await params;
  if (!isSport(sport)) notFound();
  const t = usTeams(sport)[id];
  if (!t) notFound();
  const details = usDetails(sport);
  const upcoming = t.upcoming.map((g) => details[g]).filter(Boolean);
  const s = t.standing;
  return (
    <div className="space-y-5">
      <div className="flex items-center gap-4">
        <Logo src={t.logo} alt={t.short} size={64} />
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">{t.name}</h1>
          <p className="text-sm text-ink-2">{t.division}{sport === "nba" ? ` · ${t.conference}ern Conference` : ""}</p>
        </div>
      </div>
      <div className="grid gap-3 sm:grid-cols-4">
        <div className="card p-4"><Stat label="Record" value={rec(s)} sub={`${s.conf_rank}${["st", "nd", "rd"][s.conf_rank - 1] ?? "th"} in ${t.conference}`} /></div>
        <div className="card p-4"><Stat label="Elo rating" value={t.elo_now.toFixed(0)} /></div>
        <div className="card p-4"><Stat label="Home · Away" value={`${rec(s.home)} · ${rec(s.away)}`} /></div>
        <div className="card p-4"><Stat label="Points per game" value={`${s.pf_pg ?? "–"} – ${s.pa_pg ?? "–"}`} sub={`diff ${s.diff > 0 ? "+" : ""}${s.diff}`} /></div>
      </div>
      <div className="grid gap-5 lg:grid-cols-2">
        <Card title="Elo rating over time"><EloChart data={t.elo_history.map((e) => ({ ...e, div: "" }))} /><p className="mt-2 text-xs text-muted">Last three seasons.</p></Card>
        <Card title="Form trend (rolling 5-game point differential)">
          <MarginChart data={t.trend} />
          <div className="mt-2 flex flex-wrap gap-1">{t.trend.slice(-10).map((f) => <WLPill key={f.date} r={f.result} title={`${f.date} ${f.venue === "H" ? "v" : "@"} ${f.opponent} ${f.pf}–${f.pa}`} />)}</div>
        </Card>
      </div>
      <Card title="Upcoming games">
        {upcoming.length ? (
          <ul className="grid gap-2 md:grid-cols-2">
            {upcoming.map((g) => {
              const home = g.home.id === t.id;
              const p = home ? g.p_home : 1 - g.p_home;
              return (
                <li key={g.game_id}>
                  <Link href={`/${sport}/game/${g.game_id}`} className="flex items-center justify-between gap-3 rounded-lg p-2 hover:bg-surface-2">
                    <span className="flex items-center gap-2 text-sm">
                      <Logo src={(home ? g.away : g.home).logo} alt={(home ? g.away : g.home).short} size={22} />
                      {home ? "v" : "@"} {(home ? g.away : g.home).nickname}
                      <span className="text-xs text-muted">{fmtKickoff(g.kickoff_utc)}</span>
                    </span>
                    <span className={`text-sm font-semibold tabular ${p >= 0.5 ? "text-win" : "text-loss"}`}>{Math.round(p * 100)}%</span>
                  </Link>
                </li>
              );
            })}
          </ul>
        ) : <p className="text-sm text-muted">No games in the prediction window.</p>}
      </Card>
    </div>
  );
}
