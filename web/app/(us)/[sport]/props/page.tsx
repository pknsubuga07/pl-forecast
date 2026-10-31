import type { Metadata } from "next";
import { PropsBoard } from "@/components/PropsBoard";
import { Card, Stat } from "@/components/ui";
import { getProps } from "@/lib/extras";
import { fmtTime } from "@/lib/format";
import { isSport, SPORT_NAME, type Sport } from "@/lib/us";

export async function generateMetadata({ params }: PageProps<"/[sport]/props">): Promise<Metadata> {
  const { sport } = await params;
  return { title: `${SPORT_NAME[sport as Sport] ?? ""} player props` };
}

const pct = (x: number | null | undefined) => (x === null || x === undefined ? "–" : `${(x * 100).toFixed(1)}%`);
const roi = (x: number | null | undefined) => (x === null || x === undefined ? "–" : `${x >= 0 ? "+" : ""}${(x * 100).toFixed(1)}%`);

export default async function PropsPage({ params }: PageProps<"/[sport]/props">) {
  const { sport } = await params;
  if (!isSport(sport)) return null;
  const d = getProps(sport);
  const games = d.games.map((g) => ({ ...g, time: fmtTime(g.kickoff_utc) }));
  const ev = d.evaluation;
  const markets = ev ? Object.entries(ev.markets).filter(([, m]) => m.label).map(([id, m]) => ({ id, label: m.label! })) : [];
  return (
    <div className="space-y-5">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">{SPORT_NAME[sport]} player props</h1>
        <p className="mt-1 max-w-3xl text-sm text-ink-2">
          A projection for every player line DraftKings posts (via ESPN), from each player&apos;s recent games, with the
          model&apos;s chance of the over or under next to the market&apos;s. Confidence: high ≥ 62%, medium ≥ 56% for the
          model&apos;s side. Players listed Out, Doubtful or on IR are removed; Questionable and Day-To-Day are flagged.
        </p>
      </div>
      <div className="rounded-xl border border-warn/40 bg-warn/10 p-4 text-sm">
        Player lines are set by people who know about minutes limits, injuries and matchups that this model does not.{" "}
        {ev ? "Check the backtest below before trusting any lean. " : "The backtest against past lines is still being run, so these projections are unproven. "}
        Treat these as projections, not bets. Personal and educational use only; 1-800-GAMBLER if gambling stops being fun.
      </div>
      <PropsBoard games={games} markets={markets} />
      {!ev && <p className="card p-4 text-sm text-muted">Backtest in progress: projections appear once the model has been scored against past lines.</p>}
      {ev && (
        <Card title={`Backtest: fitted on ${ev.train_season}${sport === "nba" ? `-${String(ev.train_season + 1).slice(2)}` : ""} lines, scored on ${ev.test_seasons.join(" & ")}`}>
          <div className="overflow-x-auto">
            <table className="w-full min-w-[40rem] text-sm tabular">
              <thead><tr className="text-left text-xs text-muted">
                <th className="pb-2 font-normal">Market</th><th className="pb-2 text-right font-normal">Test props</th>
                <th className="pb-2 text-right font-normal">Projection miss</th><th className="pb-2 text-right font-normal">Line miss</th>
                <th className="pb-2 text-right font-normal">Log loss model / market</th>
                <th className="pb-2 text-right font-normal">Confident picks won</th><th className="pb-2 text-right font-normal">Return</th>
              </tr></thead>
              <tbody>
                {Object.entries(ev.markets).map(([id, m]) => (
                  <tr key={id} className="border-t border-line">
                    <td className="py-1.5">{m.label ?? id}</td>
                    <td className="py-1.5 text-right">{m.n_test.toLocaleString()}</td>
                    {m.note ? <td colSpan={5} className="py-1.5 text-right text-muted">{m.note}</td> : id === "anytime_td" ? (
                      <>
                        <td className="py-1.5 text-right">–</td><td className="py-1.5 text-right">–</td>
                        <td className="py-1.5 text-right">{m.log_loss_model?.toFixed(3)} / {m.log_loss_market_with_margin?.toFixed(3)}*</td>
                        <td className="py-1.5 text-right">{pct(m.hit_rate)} ({m.bets})</td><td className={`py-1.5 text-right ${(m.roi ?? 0) >= 0 ? "text-win" : "text-loss"}`}>{roi(m.roi)}</td>
                      </>
                    ) : (
                      <>
                        <td className="py-1.5 text-right">{m.mae_projection?.toFixed(2)}</td>
                        <td className="py-1.5 text-right">{m.mae_line?.toFixed(2)}</td>
                        <td className="py-1.5 text-right">{m.log_loss_model?.toFixed(3)} / {m.log_loss_market?.toFixed(3)}</td>
                        <td className="py-1.5 text-right">{pct(m.hit_rate_confident)} ({m.bets_confident})</td>
                        <td className={`py-1.5 text-right ${(m.roi_confident ?? 0) >= 0 ? "text-win" : "text-loss"}`}>{roi(m.roi_confident)}</td>
                      </>
                    )}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="mt-3 text-xs text-muted">
            &quot;Projection miss&quot; and &quot;line miss&quot; are average absolute errors against what the player actually did; a
            smaller line miss means the bookmaker&apos;s number was closer. Break-even at -110 is 52.4%.
            {sport === "nfl" && " * Anytime TD is a one-sided market, so the market's log loss still includes its margin."}
            {Object.values(ev.markets).some((m) => m.assumed_prices) &&
              " ESPN does not keep the prices of settled NFL props, only the lines, so NFL returns assume the standard -110 on both sides."}
          </p>
        </Card>
      )}
      <div className="grid gap-3 sm:grid-cols-3">
        <div className="card p-4"><Stat label="Live props settled" value={d.record?.n ?? 0} sub="medium/high picks frozen at tip-off" /></div>
        <div className="card p-4"><Stat label="Live hit rate" value={d.record ? pct(d.record.hit_rate) : "–"} /></div>
        <div className="card p-4"><Stat label="Live return" value={d.record ? roi(d.record.roi) : "–"} sub="per $1 at the frozen price" /></div>
      </div>
    </div>
  );
}
