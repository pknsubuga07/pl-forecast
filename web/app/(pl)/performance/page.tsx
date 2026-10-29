import type { Metadata } from "next";
import { CalibrationChart } from "@/components/charts";
import { Card, Stat } from "@/components/ui";
import { getPerformance } from "@/lib/data";
import { fmtDate } from "@/lib/format";
import type { CalibrationBin, Metrics } from "@/lib/types";

export const metadata: Metadata = { title: "Model performance" };

const ORDER = ["home", "elo", "dc", "logreg", "gbm", "ensemble", "market", "market_close"];

function MetricTable({ metrics, labels, highlight = "ensemble" }: { metrics: Record<string, Metrics>; labels: Record<string, string>; highlight?: string }) {
  const keys = ORDER.filter((k) => metrics[k]);
  const best = (f: keyof Metrics, lower: boolean) =>
    keys.filter((k) => !k.startsWith("market")).reduce((a, b) => ((lower ? metrics[b][f] < metrics[a][f] : metrics[b][f] > metrics[a][f]) ? b : a));
  const bests = { log_loss: best("log_loss", true), brier: best("brier", true), rps: best("rps", true), accuracy: best("accuracy", false) };
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[34rem] text-sm tabular">
        <thead>
          <tr className="text-left text-xs text-muted">
            <th className="pb-2 font-normal">Model</th>
            <th className="pb-2 pl-4 text-right font-normal">Log loss ↓</th>
            <th className="pb-2 pl-4 text-right font-normal">Brier ↓</th>
            <th className="pb-2 pl-4 text-right font-normal">RPS ↓</th>
            <th className="pb-2 pl-4 text-right font-normal">Accuracy ↑</th>
          </tr>
        </thead>
        <tbody>
          {keys.map((k) => {
            const m = metrics[k];
            const mk = k.startsWith("market");
            return (
              <tr key={k} className={`border-t border-line ${k === highlight ? "bg-accent/8 font-medium" : ""} ${mk ? "text-ink-2" : ""}`}>
                <td className="py-2 pr-3">{labels[k] ?? k}</td>
                {(["log_loss", "brier", "rps", "accuracy"] as const).map((f) => (
                  <td key={f} className={`py-2 pl-4 text-right ${bests[f] === k ? "font-semibold text-ink" : ""}`}>
                    {f === "accuracy" ? `${(m[f] * 100).toFixed(1)}%` : m[f].toFixed(4)}
                  </td>
                ))}
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

export default function PerformancePage() {
  const perf = getPerformance();
  const ev = perf.evaluation;
  if (!ev) return <p className="card p-6 text-sm text-muted">The evaluation has not been run yet.</p>;
  const t = ev.blocks.test;
  const ens = t.metrics.ensemble;
  const mk = t.metrics.market;
  const w = ev.hyperparams.ensemble_weights;
  const calib = (k: string): CalibrationBin[] => ev.calibration_test[k] ?? [];
  const live = perf.live.live;
  const better = ORDER.filter((k) => !k.startsWith("market") && k !== "ensemble" && t.metrics[k] && t.metrics[k].log_loss < ens.log_loss)
    .map((k) => ev.labels[k] ?? k);

  return (
    <div className="space-y-5">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Model performance</h1>
        <p className="mt-1 max-w-3xl text-sm text-ink-2">
          Every number here is out-of-sample: for each season the models were trained only on earlier seasons, and
          settings were chosen on {ev.blocks.validation.seasons[0]} to {ev.blocks.validation.seasons.at(-1)} before the
          test seasons were scored. Lower log loss, Brier score and ranked probability score (RPS) mean better
          probabilities; they matter more than accuracy.
        </p>
      </div>

      <div className="grid gap-3 sm:grid-cols-4">
        <div className="card p-4"><Stat label="Test log loss (model)" value={ens.log_loss.toFixed(3)} sub={`bookmakers ${mk.log_loss.toFixed(3)}`} /></div>
        <div className="card p-4"><Stat label="Test accuracy (model)" value={`${(ens.accuracy * 100).toFixed(1)}%`} sub={`bookmakers ${(mk.accuracy * 100).toFixed(1)}%`} /></div>
        <div className="card p-4"><Stat label="Test matches" value={t.n.toLocaleString()} sub={`${t.seasons[0]} – ${t.seasons.at(-1)}`} /></div>
        <div className="card p-4">
          <Stat label="Live record this season" value={live ? `${live.n} matches` : "Starts this week"}
            sub={live ? `log loss ${live.log_loss.toFixed(3)} · ${(live.accuracy * 100).toFixed(0)}% correct` : "frozen pre-kickoff predictions"} />
        </div>
      </div>

      <Card title={`Test seasons ${t.seasons[0]} – ${t.seasons.at(-1)} (${t.n} matches)`}>
        <MetricTable metrics={t.metrics} labels={ev.labels} />
        <p className="mt-3 text-xs text-muted">
          The honest headline: the bookmakers&apos; pre-match average is better than this model on every metric, which is
          normal for public-data models. The final ensemble ({Object.entries(w).filter(([, v]) => v > 0).map(([k, v]) => `${k} ${Math.round(v * 100)}%`).join(", ")})
          was chosen because it was best on the validation seasons.
          {better.length > 0 && ` On the test seasons ${better.join(" and ")} did slightly better; we report that rather than switch models after seeing the test results.`}{" "}
          Bold marks the best non-bookmaker value in each column.
        </p>
      </Card>

      <div className="grid gap-5 lg:grid-cols-2">
        <Card title="Calibration on test seasons">
          <CalibrationChart model={calib("ensemble")} market={calib("market")} />
          <p className="mt-2 text-xs text-muted">
            Every home, draw and away probability is grouped into 10% bins. A well-calibrated forecaster sits on the dashed
            line: events given 40% happen about 40% of the time. Bins with fewer than 20 forecasts are hidden.
          </p>
          <details className="mt-2 text-xs">
            <summary className="cursor-pointer text-ink-2">Show as table</summary>
            <table className="mt-2 w-full tabular">
              <thead><tr className="text-muted"><th className="text-left font-normal">Bin</th><th className="text-right font-normal">n</th><th className="text-right font-normal">Model predicted</th><th className="text-right font-normal">Happened</th></tr></thead>
              <tbody>
                {calib("ensemble").map((b) => (
                  <tr key={b.bin_lo} className="border-t border-line">
                    <td>{Math.round(b.bin_lo * 100)}–{Math.round(b.bin_hi * 100)}%</td>
                    <td className="text-right">{b.n}</td>
                    <td className="text-right">{(b.mean_pred * 100).toFixed(1)}%</td>
                    <td className="text-right">{(b.observed * 100).toFixed(1)}%</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </details>
        </Card>
        <Card title={`Validation seasons ${ev.blocks.validation.seasons[0]} – ${ev.blocks.validation.seasons.at(-1)}`}>
          <MetricTable metrics={ev.blocks.validation.metrics} labels={ev.labels} />
          <p className="mt-3 text-xs text-muted">Used to choose every setting, so these numbers are slightly optimistic.</p>
        </Card>
      </div>

      <Card title="Log loss by season">
        <div className="overflow-x-auto">
          <table className="w-full min-w-[36rem] text-sm tabular">
            <thead>
              <tr className="text-left text-xs text-muted">
                <th className="pb-2 font-normal">Season</th>
                <th className="pb-2 text-right font-normal">Matches</th>
                <th className="pb-2 text-right font-normal">Always home</th>
                <th className="pb-2 text-right font-normal">Elo</th>
                <th className="pb-2 text-right font-normal">Dixon-Coles</th>
                <th className="pb-2 text-right font-normal">Boosting</th>
                <th className="pb-2 text-right font-normal">Ensemble</th>
                <th className="pb-2 text-right font-normal">Bookmakers</th>
              </tr>
            </thead>
            <tbody>
              {ev.per_season.map((s) => (
                <tr key={s.season} className="border-t border-line">
                  <td className="py-1.5">
                    {s.season}
                    <span className="ml-1.5 text-[11px] text-muted">
                      {ev.blocks.validation.seasons.includes(s.season) ? "validation" : ev.blocks.test.seasons.includes(s.season) ? "test" : "in progress"}
                    </span>
                  </td>
                  <td className="py-1.5 text-right text-ink-2">{s.n}</td>
                  {["home", "elo", "dc", "gbm", "ensemble", "market"].map((k) => (
                    <td key={k} className={`py-1.5 text-right ${k === "ensemble" ? "font-medium" : "text-ink-2"}`}>{s.metrics[k]?.log_loss.toFixed(3) ?? "–"}</td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>

      <Card title="How the model works">
        <div className="grid gap-4 text-sm text-ink-2 md:grid-cols-2">
          <p>
            <b className="text-ink">Elo</b> ratings run over the Premier League and Championship together since 2004-05, so a
            promoted club arrives with the rating it earned in the Championship. <b className="text-ink">Dixon-Coles</b> fits
            attack and defence strengths from the last three seasons, weighting recent matches more and blending goals with
            shots on target (a free stand-in for xG), and gives the full scoreline distribution.
          </p>
          <p>
            A <b className="text-ink">gradient-boosted classifier</b> combines those ratings with recent form, home/away
            form, shot difference, league position, rest days including cup and European games, and promotion status. The
            final forecast averages Dixon-Coles and the boosted model. Bookmaker odds are never used as an input, so the
            comparison with the market is fair. Model {perf.model.version}, trained {fmtDate(perf.model.trained_at)} on{" "}
            {perf.model.n_train.toLocaleString()} matches.
          </p>
        </div>
      </Card>
    </div>
  );
}
