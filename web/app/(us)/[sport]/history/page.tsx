import type { Metadata } from "next";
import { RunningLossChart } from "@/components/charts";
import { Card, Stat } from "@/components/ui";
import { Logo } from "@/components/us-ui";
import { fmtDate } from "@/lib/format";
import { isSport, SPORT_NAME, usHistory, type Sport, type USHistoryGame } from "@/lib/us";

export async function generateMetadata({ params }: PageProps<"/[sport]/history">): Promise<Metadata> {
  const { sport } = await params;
  return { title: `${SPORT_NAME[sport as Sport] ?? ""} prediction history` };
}

function running(games: USHistoryGame[]) {
  const chron = [...games].reverse().filter((g) => g.log_loss !== null);
  let sm = 0, sk = 0, nk = 0;
  return chron.map((g, i) => {
    sm += g.log_loss!;
    if (g.market_p_home !== null) {
      const y = g.actual_margin > 0;
      sk += -Math.log(Math.max(y ? g.market_p_home : 1 - g.market_p_home, 1e-9));
      nk += 1;
    }
    return { n: i + 1, model: sm / (i + 1), market: nk ? sk / nk : null };
  });
}

export default async function USHistoryPage({ params }: PageProps<"/[sport]/history">) {
  const { sport } = await params;
  if (!isSport(sport)) return null;
  const h = usHistory(sport);
  const s = h.summary;
  const all = s.all;
  return (
    <div className="space-y-5">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">{SPORT_NAME[sport]} prediction history · {h.season}</h1>
        <p className="mt-1 max-w-3xl text-sm text-ink-2">
          <b>Live</b> rows are predictions frozen at tip-off / kickoff and never edited. <b>Backtest</b> rows are games
          played before this app existed, predicted by models trained only on earlier seasons: out-of-sample, but not
          published in advance.
        </p>
      </div>
      {all ? (
        <div className="grid gap-3 sm:grid-cols-4">
          <div className="card p-4"><Stat label="Games" value={all.n} sub={`${s.live?.n ?? 0} live · ${s.backtest?.n ?? 0} backtest`} /></div>
          <div className="card p-4"><Stat label="Winner picked" value={`${(all.accuracy * 100).toFixed(1)}%`} sub={all.market ? `market favourite ${(all.market.accuracy * 100).toFixed(1)}%` : undefined} /></div>
          <div className="card p-4"><Stat label="Log loss" value={all.log_loss.toFixed(3)} sub={all.market ? `market ${all.market.log_loss.toFixed(3)} (n ${all.market.n})` : undefined} /></div>
          <div className="card p-4"><Stat label="Margin error" value={`${all.margin_mae.toFixed(1)} pts`} sub="mean absolute error" /></div>
        </div>
      ) : <p className="card p-6 text-sm text-muted">No finished games yet this season.</p>}
      {h.games.length > 8 && <Card title="Running average log loss (lower is better)"><RunningLossChart data={running(h.games)} /></Card>}
      <Card title="Results">
        <div className="overflow-x-auto">
          <table className="w-full min-w-[40rem] text-sm tabular">
            <thead>
              <tr className="text-left text-xs text-muted">
                <th className="pb-2 font-normal">Date</th><th className="pb-2 font-normal">Game</th>
                <th className="pb-2 text-right font-normal">Home win (model)</th><th className="pb-2 text-right font-normal">Market</th>
                <th className="pb-2 text-right font-normal">Margin pred / actual</th><th className="pb-2 text-center font-normal">Pick</th>
              </tr>
            </thead>
            <tbody>
              {h.games.map((g) => (
                <tr key={g.game_id} className="border-t border-line">
                  <td className="py-2 pr-2 text-xs text-muted whitespace-nowrap">
                    {fmtDate(g.kickoff_utc)}
                    <span className={`ml-1.5 rounded px-1 py-0.5 text-[10px] font-medium ${g.mode === "live" ? "bg-accent/15 text-accent" : "bg-surface-2 text-muted"}`}>{g.mode}</span>
                  </td>
                  <td className="py-2 pr-2">
                    <div className="flex items-center gap-1.5 whitespace-nowrap">
                      <Logo src={g.away_logo} alt={g.away} size={18} />
                      <span className={g.actual_margin < 0 ? "font-semibold" : ""}>{g.away} {g.away_score}</span>
                      <span className="text-muted">@</span>
                      <span className={g.actual_margin > 0 ? "font-semibold" : ""}>{g.home} {g.home_score}</span>
                      <Logo src={g.home_logo} alt={g.home} size={18} />
                    </div>
                  </td>
                  <td className="py-2 text-right">{Math.round(g.p_home * 100)}%</td>
                  <td className="py-2 text-right text-ink-2">{g.market_p_home === null ? "–" : `${Math.round(g.market_p_home * 100)}%`}</td>
                  <td className="py-2 text-right text-ink-2">{g.pred_margin > 0 ? "+" : ""}{g.pred_margin.toFixed(1)} / {g.actual_margin > 0 ? "+" : ""}{g.actual_margin}</td>
                  <td className="py-2 text-center">
                    {g.correct === null ? <span className="text-xs text-muted">tie</span> : (
                      <span className={`text-xs font-medium ${g.correct ? "text-win" : "text-loss"}`}>{g.correct ? "✓" : "✗"} {g.p_home >= 0.5 ? g.home : g.away}</span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="mt-2 text-xs text-muted">Margins are from the home team&apos;s point of view.</p>
      </Card>
    </div>
  );
}
