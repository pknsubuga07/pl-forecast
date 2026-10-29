import type { Metadata } from "next";
import { RunningLossChart } from "@/components/charts";
import { Card, Crest, ProbBar, Stat } from "@/components/ui";
import { getHistory } from "@/lib/data";
import { fmtDate, pct3 } from "@/lib/format";
import type { HistoryMatch } from "@/lib/types";

export const metadata: Metadata = { title: "Prediction history" };

function running(matches: HistoryMatch[]) {
  const chron = [...matches].reverse();
  let sm = 0, sk = 0, nk = 0;
  return chron.map((m, i) => {
    sm += m.log_loss;
    const y = "HDA".indexOf(m.result);
    if (m.market_p) {
      sk += -Math.log(Math.max(m.market_p[y], 1e-12));
      nk += 1;
    }
    return { n: i + 1, model: sm / (i + 1), market: nk ? sk / nk : null };
  });
}

export default function HistoryPage() {
  const h = getHistory();
  const s = h.summary;
  const all = s.all;
  const correct = h.matches.filter((m) => m.correct).length;
  return (
    <div className="space-y-5">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Prediction history · {h.season}</h1>
        <p className="mt-1 max-w-3xl text-sm text-ink-2">
          What the model said before each finished match, against what happened. <b>Live</b> rows are predictions frozen at
          kickoff and never edited afterwards (the ledger is version-controlled). <b>Backtest</b> rows cover matches played
          before this app existed: they come from the same walk-forward models trained only on earlier seasons, so they are
          out-of-sample but were not published in advance.
        </p>
      </div>
      {all ? (
        <div className="grid gap-3 sm:grid-cols-4">
          <div className="card p-4"><Stat label="Matches" value={all.n} sub={`${s.live?.n ?? 0} live · ${s.backtest?.n ?? 0} backtest`} /></div>
          <div className="card p-4"><Stat label="Correct outcome" value={`${correct} / ${all.n}`} sub={`${(all.accuracy * 100).toFixed(1)}%`} /></div>
          <div className="card p-4"><Stat label="Log loss" value={all.log_loss.toFixed(3)} sub={all.market ? `bookmakers ${all.market.log_loss.toFixed(3)} (same ${all.market.n})` : undefined} /></div>
          <div className="card p-4"><Stat label="Brier · RPS" value={`${all.brier.toFixed(3)} · ${all.rps.toFixed(3)}`} sub={all.market ? `bookmakers ${all.market.brier.toFixed(3)} · ${all.market.rps.toFixed(3)}` : undefined} /></div>
        </div>
      ) : (
        <p className="card p-6 text-sm text-muted">No finished matches yet this season.</p>
      )}

      {h.matches.length > 5 && (
        <Card title="Running average log loss (lower is better)">
          <RunningLossChart data={running(h.matches)} />
        </Card>
      )}

      <Card title="Results">
        <div className="overflow-x-auto">
          <table className="w-full min-w-[40rem] text-sm">
            <thead>
              <tr className="text-left text-xs text-muted">
                <th className="pb-2 font-normal">Date</th>
                <th className="pb-2 font-normal">Match</th>
                <th className="w-48 pb-2 font-normal">Model H / D / A</th>
                <th className="pb-2 text-right font-normal">Market H / D / A</th>
                <th className="pb-2 text-center font-normal">Pick</th>
                <th className="pb-2 text-right font-normal">Log loss</th>
              </tr>
            </thead>
            <tbody>
              {h.matches.map((m) => {
                const mk = m.market_p ? pct3(m.market_p) : null;
                return (
                  <tr key={m.match_id} className="border-t border-line align-middle">
                    <td className="py-2 pr-2 text-xs text-muted tabular whitespace-nowrap">
                      {fmtDate(m.kickoff_utc)}
                      <span className={`ml-1.5 rounded px-1 py-0.5 text-[10px] font-medium ${m.mode === "live" ? "bg-accent/15 text-accent" : "bg-surface-2 text-muted"}`}>
                        {m.mode}
                      </span>
                    </td>
                    <td className="py-2 pr-2">
                      <div className="flex items-center gap-1.5 whitespace-nowrap">
                        <Crest team={{ crest: m.home_crest, short: m.home_short, name: m.home }} size={18} />
                        <span className={m.result === "H" ? "font-semibold" : ""}>{m.home_short}</span>
                        <b className="tabular">{m.home_goals}–{m.away_goals}</b>
                        <span className={m.result === "A" ? "font-semibold" : ""}>{m.away_short}</span>
                        <Crest team={{ crest: m.away_crest, short: m.away_short, name: m.away }} size={18} />
                      </div>
                    </td>
                    <td className="py-2 pr-2"><ProbBar p={m.p} height={16} compact /></td>
                    <td className="py-2 pr-2 text-right text-xs text-ink-2 tabular">{mk ? `${mk[0]} / ${mk[1]} / ${mk[2]}` : "–"}</td>
                    <td className="py-2 text-center">
                      <span className={`inline-flex items-center gap-1 text-xs font-medium ${m.correct ? "text-win" : "text-loss"}`}>
                        <span aria-hidden>{m.correct ? "✓" : "✗"}</span>
                        {m.predicted}
                      </span>
                    </td>
                    <td className="py-2 text-right text-xs tabular text-ink-2">{m.log_loss.toFixed(2)}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </Card>
    </div>
  );
}
