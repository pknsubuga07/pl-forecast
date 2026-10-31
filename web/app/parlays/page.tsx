import type { Metadata } from "next";
import Link from "next/link";
import { Card, ConfidenceBadge, Stat } from "@/components/ui";
import { getParlays, SPORT_LABEL, type BTSummary, type Parlay } from "@/lib/extras";
import { fmtTime, fmtUpdated } from "@/lib/format";

export const metadata: Metadata = { title: "Daily parlays" };

const dayFmt = new Intl.DateTimeFormat("en-US", { timeZone: "UTC", weekday: "long", month: "long", day: "numeric" });
const pct = (x: number | null | undefined, d = 0) => (x === null || x === undefined ? "–" : `${(x * 100).toFixed(d)}%`);
const roi = (x: number) => `${x >= 0 ? "+" : ""}${(x * 100).toFixed(1)}%`;

function ParlayCard({ p }: { p: Parlay }) {
  const stat = p.status !== "open" ? p.status : null;
  return (
    <article className="card p-4">
      <div className="mb-3 flex items-center justify-between gap-2">
        <div>
          <div className="text-xs uppercase tracking-wide text-muted">{p.tag}</div>
          <div className="text-sm font-semibold">{p.n_legs}-leg parlay</div>
        </div>
        <div className="text-right">
          <div className="text-xl font-semibold tabular">{p.odds.toFixed(2)}</div>
          <div className="text-[11px] text-muted">decimal odds · $10 pays ${(p.odds * 10).toFixed(2)}</div>
        </div>
      </div>
      <ul className="space-y-2">
        {p.legs.map((l) => (
          <li key={l.game_id} className="flex items-center justify-between gap-2 rounded-lg bg-surface-2 px-3 py-2 text-sm">
            <div className="min-w-0">
              <Link href={l.href || "#"} className="font-medium hover:underline">{l.label}</Link>
              <div className="truncate text-xs text-muted">{SPORT_LABEL[l.sport]} · {l.matchup} · {fmtTime(l.kickoff_utc)}</div>
            </div>
            <div className="shrink-0 text-right">
              <div className="text-sm font-semibold tabular">{pct(l.p_model)}</div>
              <div className="text-[11px] text-muted tabular">market {pct(l.p_market)} · {l.odds.toFixed(2)}</div>
            </div>
          </li>
        ))}
      </ul>
      <div className="mt-3 grid grid-cols-3 gap-2 text-center text-xs">
        <div className="rounded-lg border border-line p-2"><div className="text-muted">Model chance</div><div className="text-base font-semibold tabular">{pct(p.p_model, 1)}</div></div>
        <div className="rounded-lg border border-line p-2"><div className="text-muted">Market chance</div><div className="text-base font-semibold tabular">{pct(p.p_market, 1)}</div></div>
        <div className="rounded-lg border border-line p-2"><div className="text-muted">Break-even</div><div className="text-base font-semibold tabular">{pct(1 / p.odds, 1)}</div></div>
      </div>
      <div className="mt-2 flex flex-wrap gap-1.5">
        {[...new Set(p.legs.map((l) => l.confidence))].map((c) => <ConfidenceBadge key={c} level={c} short />)}
        {stat && <span className={`rounded-full px-2 py-0.5 text-[11px] font-medium ${stat === "won" ? "bg-win/15 text-win" : stat === "lost" ? "bg-loss/15 text-loss" : "bg-surface-2 text-muted"}`}>{stat}</span>}
      </div>
    </article>
  );
}

function BTRow({ label, s }: { label: string; s: BTSummary }) {
  return (
    <tr className="border-t border-line">
      <td className="py-1.5">{label}</td>
      <td className="py-1.5 text-right">{s.n.toLocaleString()}</td>
      <td className="py-1.5 text-right">{pct(s.hit_rate, 1)}</td>
      <td className="py-1.5 text-right text-ink-2">{pct(s.expected_hit_rate_model, 1)}</td>
      <td className="py-1.5 text-right text-ink-2">{s.avg_odds.toFixed(2)}</td>
      <td className={`py-1.5 text-right font-medium ${s.roi >= 0 ? "text-win" : "text-loss"}`}>{roi(s.roi)}</td>
    </tr>
  );
}

export default function ParlaysPage() {
  const d = getParlays();
  const bt = d.backtest;
  return (
    <main className="mx-auto w-full max-w-6xl flex-1 space-y-6 px-4 py-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Daily parlays</h1>
        <p className="mt-1 max-w-3xl text-sm text-ink-2">
          5–10 combinations per day built only from <b>medium- and high-confidence</b> picks across the Premier League, NBA
          and NFL, using that day&apos;s bookmaker prices. Each shows the model&apos;s chance it wins, the market&apos;s chance,
          and the break-even chance implied by the payout. Legs are treated as independent. A day&apos;s parlays are frozen
          when its first game starts.
        </p>
        {d.generated_at && <p className="mt-1 text-xs text-muted">Updated {fmtUpdated(d.generated_at)}</p>}
      </div>

      <div className="rounded-xl border border-warn/40 bg-warn/10 p-4 text-sm">
        <b>Read this first.</b> The model is less accurate than the betting market, and every leg adds the bookmaker&apos;s
        margin again. In the backtest below these parlays <b>lost {bt ? roi(-bt.all.roi).replace("+", "") : "money"} of every
        dollar staked</b>. They are here to show the most likely combinations, not as a way to make money. Personal and
        educational use only. If gambling stops being fun, call 1-800-GAMBLER.
      </div>

      {d.days.length === 0 && <p className="card p-6 text-sm text-muted">No games in the next few days.</p>}
      {d.days.map((day) => (
        <section key={day.day}>
          <div className="mb-3 flex flex-wrap items-baseline justify-between gap-2">
            <h2 className="text-lg font-semibold">{dayFmt.format(new Date(`${day.day}T12:00:00Z`))}</h2>
            <span className="text-xs text-muted">{day.n_games} games priced · {day.n_eligible} medium/high-confidence legs</span>
          </div>
          {day.parlays.length ? (
            <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">{day.parlays.map((p) => <ParlayCard key={p.parlay_id} p={p} />)}</div>
          ) : (
            <p className="card p-4 text-sm text-muted">Not enough medium/high-confidence games with prices for a parlay this day.</p>
          )}
        </section>
      ))}

      {bt && (
        <Card title={`Backtest: ${bt.all.n.toLocaleString()} parlays over ${bt.days} days`}>
          <p className="mb-3 text-xs text-muted">{bt.seasons}. Built with exactly the same rules, from predictions made by models trained only on earlier seasons, settled at the bookmaker prices of the time ($1 per parlay).</p>
          <div className="overflow-x-auto">
            <table className="w-full min-w-[34rem] text-sm tabular">
              <thead><tr className="text-left text-xs text-muted">
                <th className="pb-2 font-normal">Type</th><th className="pb-2 text-right font-normal">Parlays</th><th className="pb-2 text-right font-normal">Won</th>
                <th className="pb-2 text-right font-normal">Model expected</th><th className="pb-2 text-right font-normal">Avg odds</th><th className="pb-2 text-right font-normal">Return</th>
              </tr></thead>
              <tbody>
                <BTRow label="All parlays" s={bt.all} />
                {Object.entries(bt.by_legs).map(([k, s]) => <BTRow key={k} label={`${k}-leg`} s={s} />)}
                {Object.entries(bt.by_tag).map(([k, s]) => <BTRow key={k} label={k} s={s} />)}
              </tbody>
            </table>
          </div>
          <p className="mt-3 text-xs text-muted">
            &quot;Return&quot; is profit per dollar staked; negative means money lost. Picks the model likes more than the market
            (&quot;Best value&quot;) did worst: when the two disagree, the market has usually been right.
          </p>
        </Card>
      )}

      <div className="grid gap-3 sm:grid-cols-3">
        <div className="card p-4"><Stat label="Live parlays settled" value={d.record ? d.record.n : 0} sub={d.record ? `${d.record.won} won` : "record starts with today's slate"} /></div>
        <div className="card p-4"><Stat label="Live hit rate" value={d.record ? pct(d.record.hit_rate, 1) : "–"} sub={d.record ? `model expected ${pct(d.record.expected_hit_rate, 1)}` : undefined} /></div>
        <div className="card p-4"><Stat label="Live return" value={d.record ? roi(d.record.roi) : "–"} sub="per $1 at the frozen prices" /></div>
      </div>

      {d.history.length > 0 && (
        <Card title="Settled parlays">
          <ul className="divide-y divide-line text-sm">
            {d.history.map((p) => (
              <li key={p.parlay_id} className="flex items-center justify-between gap-3 py-2">
                <span className="min-w-0 truncate"><span className="text-xs text-muted">{p.day}</span> · {p.legs.map((l) => l.label).join(" + ")}</span>
                <span className={`shrink-0 text-xs font-semibold ${p.status === "won" ? "text-win" : p.status === "lost" ? "text-loss" : "text-muted"}`}>{p.status} @ {p.odds.toFixed(2)}</span>
              </li>
            ))}
          </ul>
        </Card>
      )}
    </main>
  );
}
