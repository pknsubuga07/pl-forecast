import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { MatchSelector } from "@/components/MatchSelector";
import { Card, ConfidenceBadge, Disagree } from "@/components/ui";
import { Logo, Row, WLPill } from "@/components/us-ui";
import { fmtDate, fmtKickoff, num, signedPts } from "@/lib/format";
import { isSport, modelSpread, rec, SPORTS, spreadText, usDetails, usGames, type Sport, type USGameDetail, type USSide } from "@/lib/us";

export async function generateStaticParams({ params }: { params: { sport: string } }) {
  const sports = params?.sport ? [params.sport as Sport] : SPORTS;
  const out = sports.flatMap((s) => usGames(s).map((g) => ({ sport: s, id: g.game_id })));
  return out.length ? out : sports.map((s) => ({ sport: s, id: "none" }));
}

export async function generateMetadata({ params }: PageProps<"/[sport]/game/[id]">): Promise<Metadata> {
  const { sport, id } = await params;
  const g = isSport(sport) ? usDetails(sport)[id] : undefined;
  return { title: g ? `${g.away.nickname} @ ${g.home.nickname}` : "Game" };
}

const CONF_HELP = { high: "the favourite is at least 75%", medium: "the favourite is at least 62%", low: "close to a coin flip" };
const COMP = { elo: "Elo", margin: "Margin model", gbm: "Gradient boosting" } as Record<string, string>;
const ml = (x: number) => (x > 0 ? `+${x}` : `${x}`);

export default async function GamePage({ params }: PageProps<"/[sport]/game/[id]">) {
  const { sport, id } = await params;
  if (!isSport(sport)) notFound();
  const g = usDetails(sport)[id];
  if (!g) {
    if (id === "none") return <p className="card p-6 text-sm text-muted">No upcoming games right now. <Link className="underline" href={`/${sport}`}>Back</Link></p>;
    notFound();
  }
  const options = usGames(sport).map((x) => ({ id: x.game_id, label: `${fmtDate(x.kickoff_utc)} · ${x.away.short} @ ${x.home.short}` }));
  const pH = Math.round(g.p_home * 100);
  const fav = g.p_home >= 0.5 ? g.home : g.away;
  const c = g.context;
  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <Link href={`/${sport}`} className="text-sm text-ink-2 hover:text-ink">← All games</Link>
        <MatchSelector current={g.game_id} options={options} basePath={`/${sport}/game`} />
      </div>

      <section className="card overflow-hidden">
        <div className="p-5 sm:p-6">
          <p className="text-center text-xs text-muted">
            {g.week ? `Week ${g.week} · ` : ""}{g.playoff ? "Playoffs · " : ""}<time dateTime={g.kickoff_utc}>{fmtKickoff(g.kickoff_utc)} ET</time>
            {g.venue ? ` · ${g.venue}` : ""}{g.neutral ? " (neutral site)" : ""}
          </p>
          <div className="mt-4 grid grid-cols-[1fr_auto_1fr] items-center gap-3">
            <TeamHead sport={sport} t={g.away} side="Away" qb={g.away_qb} />
            <div className="text-center">
              <div className="text-xs text-muted">Projected</div>
              <div className="whitespace-nowrap text-xl font-semibold tabular sm:text-2xl">{Math.round(g.pred_away_score)} – {Math.round(g.pred_home_score)}</div>
            </div>
            <TeamHead sport={sport} t={g.home} side="Home" qb={g.home_qb} />
          </div>
          <div className="mt-6">
            <div className="flex w-full gap-[2px] overflow-hidden rounded-[5px]" style={{ height: 34 }} role="img" aria-label={`${g.away.short} ${100 - pH}%, ${g.home.short} ${pH}%`}>
              <div className="flex items-center bg-away pl-2 text-xs font-semibold text-white" style={{ width: `${100 - pH}%` }}>{100 - pH >= 10 ? `${100 - pH}%` : ""}</div>
              <div className="flex items-center justify-end bg-home pr-2 text-xs font-semibold text-white" style={{ width: `${pH}%` }}>{pH >= 10 ? `${pH}%` : ""}</div>
            </div>
            <div className="mt-2 flex justify-between text-sm tabular">
              <span><b className="text-away">{100 - pH}%</b> {g.away.short} win</span>
              <span><b className="text-home">{pH}%</b> {g.home.short} win</span>
            </div>
          </div>
        </div>
        <div className="grid gap-4 border-t border-line bg-surface-2/50 p-5 sm:grid-cols-[auto_1fr] sm:p-6">
          <div className="space-y-2">
            <div className="text-xs text-muted">Predicted winner</div>
            <div className="text-lg font-semibold">{fav.name}</div>
            <ConfidenceBadge level={g.confidence} />
            <p className="max-w-[16rem] text-xs text-muted">{g.confidence[0].toUpperCase() + g.confidence.slice(1)}: {CONF_HELP[g.confidence]}.</p>
          </div>
          <div>
            <div className="text-xs text-muted">Why</div>
            <p className="mt-1 text-[15px] leading-relaxed">{g.explanation}</p>
          </div>
        </div>
      </section>

      <div className="grid gap-5 lg:grid-cols-2">
        <Card title="Model vs betting line" action={g.disagreement ? <Disagree /> : undefined}>
          <table className="w-full text-sm tabular">
            <thead><tr className="text-xs text-muted"><th className="pb-2 text-left font-normal"></th><th className="pb-2 text-right font-normal">Model</th><th className="pb-2 text-right font-normal">Market</th></tr></thead>
            <tbody>
              <Row label={`${g.home.short} win probability`} home={`${pH}%`} away={g.market ? `${Math.round(g.market.p_home * 100)}%` : "–"} />
              <Row label="Spread" home={modelSpread(g.pred_margin, g.home.short, g.away.short)} away={spreadText(g.market_spread_home, g.home.short, g.away.short)} />
              <Row label="Total points" home={g.pred_total.toFixed(1)} away={g.market_total ?? "–"} />
              {g.market && <Row label="Moneyline" home="" away={`${g.home.short} ${ml(g.market.home_ml)} · ${g.away.short} ${ml(g.market.away_ml)}`} />}
            </tbody>
          </table>
          <p className="mt-3 text-xs text-muted">
            {g.market
              ? <>{g.market.label}. Moneyline margin of {(g.market.overround * 100).toFixed(1)}% removed. {g.market ? `Gap ${signedPts(g.p_home - g.market.p_home)} on ${g.home.short} winning` : ""}. </>
              : "No betting line stored yet for this game. "}
            Betting markets have been more accurate than this model historically (see Performance), so a big gap more often
            means missing information (injuries, rest decisions) than a mispriced line.
          </p>
        </Card>
        <Card title="Recent form (last 5)">
          <div className="space-y-4">
            <Form name={g.away.name} s={c.away} />
            <Form name={g.home.name} s={c.home} />
          </div>
        </Card>
      </div>

      <div className="grid gap-5 lg:grid-cols-2">
        <Card title="Season so far">
          <table className="w-full text-sm tabular">
            <thead><tr className="text-xs text-muted"><th className="pb-2 text-left font-normal"></th><th className="pb-2 text-right font-medium text-away">{g.away.short}</th><th className="pb-2 text-right font-medium text-home">{g.home.short}</th></tr></thead>
            <tbody>
              <Row label="Record" home={rec(c.away.season)} away={rec(c.home.season)} />
              <Row label="Conference rank" home={g.away.record.conf_rank ?? "–"} away={g.home.record.conf_rank ?? "–"} />
              <Row label="Last 10" home={rec(c.away.last10)} away={rec(c.home.last10)} />
              <Row label="Streak" home={c.away.streak ?? "–"} away={c.home.streak ?? "–"} />
              <Row label="Points for / game" home={num(c.away.season.pf_pg)} away={num(c.home.season.pf_pg)} />
              <Row label="Points against / game" home={num(c.away.season.pa_pg)} away={num(c.home.season.pa_pg)} />
              <Row label="Average margin" home={num(c.away.margin_pg)} away={num(c.home.margin_pg)} />
            </tbody>
          </table>
        </Card>
        <Card title={`${g.home.short} at home · ${g.away.short} on the road`}>
          <table className="w-full text-sm tabular">
            <thead><tr className="text-xs text-muted"><th className="pb-2 text-left font-normal"></th><th className="pb-2 text-right font-normal">This season</th><th className="pb-2 text-right font-normal">Last season</th></tr></thead>
            <tbody>
              <Row label={`${g.home.short} at home`} home={`${rec(c.home.venue_this)} · ${num(c.home.venue_this.pf_pg)}–${num(c.home.venue_this.pa_pg)}`} away={rec(c.home.venue_last)} />
              <Row label={`${g.away.short} away`} home={`${rec(c.away.venue_this)} · ${num(c.away.venue_this.pf_pg)}–${num(c.away.venue_this.pa_pg)}`} away={rec(c.away.venue_last)} />
            </tbody>
          </table>
          <p className="mt-2 text-xs text-muted">W-L, then points scored–allowed per game. Regular season and playoffs.</p>
          <div className="mt-4 grid gap-3 sm:grid-cols-2">
            {[[g.away.name, c.away], [g.home.name, c.home]].map(([name, s]) => {
              const lg = (s as USSide).last_game;
              return (
                <div key={name as string} className="rounded-lg bg-surface-2 p-3">
                  <div className="text-xs text-muted">Rest · {name as string}</div>
                  {lg ? (
                    <>
                      <div className="text-xl font-semibold tabular">{lg.days.toFixed(1)} <span className="text-sm font-normal text-ink-2">days</span>
                        {sport === "nba" && lg.days < 1.6 && <span className="ml-2 rounded bg-warn/15 px-1.5 py-0.5 text-[11px] text-warn">back-to-back</span>}
                      </div>
                      <div className="text-xs text-ink-2">Last played {lg.opponent}, {fmtDate(lg.date)}</div>
                    </>
                  ) : <div className="text-sm text-muted">First game of the season</div>}
                </div>
              );
            })}
          </div>
        </Card>
      </div>

      <div className="grid gap-5 lg:grid-cols-2">
        <Card title={`Head to head (last ${c.h2h.meetings.length})`}>
          {c.h2h.meetings.length ? (
            <>
              <div className="mb-3 flex gap-4 text-sm tabular">
                <span><b className="text-home">{c.h2h.home_wins}</b> {g.home.short} wins</span>
                <span><b className="text-away">{c.h2h.away_wins}</b> {g.away.short} wins</span>
              </div>
              <ul className="divide-y divide-line text-sm">
                {c.h2h.meetings.map((m) => (
                  <li key={m.date} className="flex items-center gap-2 py-1.5">
                    <WLPill r={m.result_for_home_team} title={`Result for ${g.home.name}`} />
                    <span className="w-24 shrink-0 text-xs text-muted tabular">{fmtDate(m.date)}</span>
                    <span className="flex-1 tabular">{m.away} {m.away_score} @ {m.home} {m.home_score}</span>
                    {m.playoff && <span className="text-[11px] text-muted">playoffs</span>}
                  </li>
                ))}
              </ul>
              <p className="mt-2 text-xs text-muted">W/L from {g.home.name}&apos;s point of view.</p>
            </>
          ) : <p className="text-sm text-muted">No meetings in the data.</p>}
        </Card>
        <Card title="What moves this prediction">
          <Factors g={g} />
          <ul className="mt-5 space-y-2 border-t border-line pt-4 text-xs">
            {Object.entries(g.components).map(([k, p]) => (
              <li key={k} className="flex items-center justify-between gap-2">
                <span className="text-ink-2">{COMP[k] ?? k} <span className="text-muted">(weight {Math.round((g.weights[k] ?? 0) * 100)}%)</span></span>
                <span className="tabular">{g.home.short} {Math.round(p * 100)}%</span>
              </li>
            ))}
          </ul>
          <p className="mt-2 text-xs text-muted">Model version {g.model_version}. Weights chosen on the 2016–2020 validation seasons.</p>
        </Card>
      </div>
    </div>
  );
}

function TeamHead({ sport, t, side, qb }: { sport: Sport; t: USGameDetail["home"]; side: string; qb: string | null }) {
  return (
    <Link href={`/${sport}/teams/${t.id}`} className="flex min-w-0 flex-col items-center gap-2 text-center hover:opacity-80">
      <Logo src={t.logo} alt={t.short} size={56} />
      <div className="min-w-0">
        <div className="text-base font-semibold sm:text-lg">
          <span className="sm:hidden">{t.nickname}</span>
          <span className="hidden sm:inline">{t.name}</span>
        </div>
        <div className="text-xs text-muted">{side} · {rec(t.record)}</div>
        {qb && <div className="text-xs text-muted">QB {qb}</div>}
      </div>
    </Link>
  );
}

function Form({ name, s }: { name: string; s: USSide }) {
  return (
    <div>
      <div className="mb-1.5 text-sm font-medium">{name}</div>
      <div className="flex flex-wrap gap-1.5">
        {s.form.map((f) => (
          <div key={f.date} className="flex items-center gap-1.5 rounded-lg bg-surface-2 py-1 pl-1 pr-2 text-xs">
            <WLPill r={f.result} title={fmtDate(f.date)} />
            <span className="tabular">{f.pf}–{f.pa}</span>
            <span className="text-muted">{f.venue === "H" ? "v" : "@"} {f.opponent}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

function Factors({ g }: { g: USGameDetail }) {
  const items = g.factors.filter((f) => Math.abs(f.effect_home) >= 0.002).slice(0, 6);
  const max = Math.max(0.05, ...items.map((f) => Math.abs(f.effect_home)));
  return (
    <>
      <div className="mb-2 flex justify-between text-[11px] text-muted">
        <span className="text-away">← favours {g.away.short}</span>
        <span className="text-home">favours {g.home.short} →</span>
      </div>
      <ul className="space-y-2.5">
        {items.map((f) => {
          const w = (Math.abs(f.effect_home) / max) * 50;
          const home = f.effect_home > 0;
          return (
            <li key={f.group} title={f.text}>
              <div className="mb-1 flex justify-between text-xs">
                <span className="text-ink-2">{f.label}</span>
                <span className="tabular text-muted">{signedPts(f.effect_home)}</span>
              </div>
              <div className="relative h-2.5 rounded-full bg-surface-2">
                <span className="absolute inset-y-0 left-1/2 w-px bg-line" />
                <span className={`absolute inset-y-0 rounded-[4px] ${home ? "bg-home" : "bg-away"}`}
                  style={home ? { left: "50%", width: `${w}%` } : { right: "50%", width: `${w}%` }} />
              </div>
            </li>
          );
        })}
      </ul>
      <p className="mt-3 text-xs text-muted">Change in {g.home.short}&apos;s win probability when the two teams are made equal on that group of inputs.</p>
    </>
  );
}
