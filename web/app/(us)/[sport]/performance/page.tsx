import type { Metadata } from "next";
import { CalibrationChart } from "@/components/charts";
import { Card, Stat } from "@/components/ui";
import { fmtDate } from "@/lib/format";
import { isSport, SPORT_NAME, usPerformance, type BinMetrics, type Sport, type USEvalBlock } from "@/lib/us";

export async function generateMetadata({ params }: PageProps<"/[sport]/performance">): Promise<Metadata> {
  const { sport } = await params;
  return { title: `${SPORT_NAME[sport as Sport] ?? ""} model performance` };
}

const ORDER = ["home", "elo", "margin", "gbm", "ensemble", "market"];

function Table({ b, labels }: { b: USEvalBlock; labels: Record<string, string> }) {
  const keys = ORDER.filter((k) => b.metrics[k]);
  const model = keys.filter((k) => k !== "market");
  const best = (f: keyof BinMetrics, lower: boolean) => model.reduce((a, c) => ((lower ? b.metrics[c][f] < b.metrics[a][f] : b.metrics[c][f] > b.metrics[a][f]) ? c : a));
  const bests = { log_loss: best("log_loss", true), brier: best("brier", true), accuracy: best("accuracy", false) };
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[30rem] text-sm tabular">
        <thead>
          <tr className="text-left text-xs text-muted">
            <th className="pb-2 font-normal">Model</th>
            <th className="pb-2 pl-4 text-right font-normal">Log loss ↓</th>
            <th className="pb-2 pl-4 text-right font-normal">Brier ↓</th>
            <th className="pb-2 pl-4 text-right font-normal">Winner picked ↑</th>
          </tr>
        </thead>
        <tbody>
          {keys.map((k) => (
            <tr key={k} className={`border-t border-line ${k === "ensemble" ? "bg-accent/8 font-medium" : ""} ${k === "market" ? "text-ink-2" : ""}`}>
              <td className="py-2 pr-3">{labels[k] ?? k}</td>
              {(["log_loss", "brier", "accuracy"] as const).map((f) => (
                <td key={f} className={`py-2 pl-4 text-right ${bests[f] === k ? "font-semibold text-ink" : ""}`}>
                  {f === "accuracy" ? `${(b.metrics[k][f] * 100).toFixed(1)}%` : b.metrics[k][f].toFixed(4)}
                </td>
              ))}
            </tr>
          ))}
          {!b.metrics.market && (
            <tr className="border-t border-line text-ink-2"><td className="py-2" colSpan={4}>Bookmaker moneyline: no stored odds for these seasons</td></tr>
          )}
        </tbody>
      </table>
    </div>
  );
}

function Lines({ b, sport }: { b: USEvalBlock; sport: Sport }) {
  if (!b.spread.n) return null;
  return (
    <div className="mt-4 grid gap-3 sm:grid-cols-2">
      <div className="rounded-lg bg-surface-2 p-3 text-sm">
        <div className="text-xs text-muted">Average miss on the final margin</div>
        <div className="tabular"><b>{b.spread.model_mae!.toFixed(2)}</b> pts model · {b.spread.market_mae!.toFixed(2)} pts betting spread</div>
      </div>
      {b.totals.n > 0 && (
        <div className="rounded-lg bg-surface-2 p-3 text-sm">
          <div className="text-xs text-muted">Average miss on total points</div>
          <div className="tabular"><b>{b.totals.model_mae!.toFixed(2)}</b> pts model · {b.totals.market_mae!.toFixed(2)} pts betting total</div>
        </div>
      )}
      <p className="text-xs text-muted sm:col-span-2">{b.spread.n} games with a {sport === "nfl" ? "closing" : "pre-game"} line.</p>
    </div>
  );
}

export default async function USPerformancePage({ params }: PageProps<"/[sport]/performance">) {
  const { sport } = await params;
  if (!isSport(sport)) return null;
  const perf = usPerformance(sport);
  const ev = perf.evaluation;
  if (!ev) return <p className="card p-6 text-sm text-muted">The evaluation has not been run yet.</p>;
  const t = ev.blocks.test;
  const w = ev.hyperparams.ensemble_weights;
  const live = perf.live.live;
  return (
    <div className="space-y-5">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">{SPORT_NAME[sport]} model performance</h1>
        <p className="mt-1 max-w-3xl text-sm text-ink-2">
          Walk-forward: each season is predicted by models trained only on earlier seasons. Settings were chosen on{" "}
          {ev.blocks.validation.seasons[0]}–{ev.blocks.validation.seasons.at(-1)}; the test seasons were scored once.
          Log loss and Brier score measure how good the probabilities are; lower is better.
        </p>
      </div>
      <div className="grid gap-3 sm:grid-cols-4">
        <div className="card p-4"><Stat label="Test log loss (model)" value={t.metrics.ensemble.log_loss.toFixed(3)} sub={t.metrics.market ? `market ${t.metrics.market.log_loss.toFixed(3)}` : undefined} /></div>
        <div className="card p-4"><Stat label="Winner picked (test)" value={`${(t.metrics.ensemble.accuracy * 100).toFixed(1)}%`} sub={t.metrics.market ? `market favourite ${(t.metrics.market.accuracy * 100).toFixed(1)}%` : undefined} /></div>
        <div className="card p-4"><Stat label="Test games" value={t.n.toLocaleString()} sub={`${t.seasons[0]} – ${t.seasons.at(-1)}`} /></div>
        <div className="card p-4"><Stat label="Live record" value={live ? `${live.n} games` : "Starting now"} sub={live ? `log loss ${live.log_loss.toFixed(3)}` : "frozen pre-game predictions"} /></div>
      </div>
      <Card title={`Test seasons ${t.seasons[0]} – ${t.seasons.at(-1)} (${t.n} games)`}>
        <Table b={t} labels={ev.labels} />
        <Lines b={t} sport={sport} />
        <p className="mt-3 text-xs text-muted">
          The final model averages {Object.entries(w).filter(([, v]) => v > 0).map(([k, v]) => `${k} ${Math.round(v * 100)}%`).join(", ")}.
          The betting market is better than the model on every measure, which is normal for a model without injury,
          lineup or rest-decision information. Bold marks the best non-market value.
        </p>
      </Card>
      <div className="grid gap-5 lg:grid-cols-2">
        <Card title="Calibration on test seasons (home-win probability)">
          <CalibrationChart model={ev.calibration_test.ensemble ?? []} market={ev.calibration_test.market ?? []} />
        </Card>
        <Card title={`Validation seasons ${ev.blocks.validation.seasons[0]} – ${ev.blocks.validation.seasons.at(-1)}`}>
          <Table b={ev.blocks.validation} labels={ev.labels} />
          <p className="mt-3 text-xs text-muted">Used to choose every setting, so slightly optimistic.</p>
        </Card>
      </div>
      <Card title="Log loss by season">
        <div className="overflow-x-auto">
          <table className="w-full min-w-[34rem] text-sm tabular">
            <thead><tr className="text-left text-xs text-muted">
              <th className="pb-2 font-normal">Season</th><th className="pb-2 text-right font-normal">Games</th>
              {["Elo", "Margin", "Boosting", "Ensemble", "Market"].map((h) => <th key={h} className="pb-2 text-right font-normal">{h}</th>)}
            </tr></thead>
            <tbody>
              {ev.per_season.map((s) => (
                <tr key={s.season} className="border-t border-line">
                  <td className="py-1.5">{s.season} <span className="text-[11px] text-muted">{ev.blocks.validation.seasons.includes(s.season) ? "validation" : t.seasons.includes(s.season) ? "test" : "in progress"}</span></td>
                  <td className="py-1.5 text-right text-ink-2">{s.n}</td>
                  {["elo", "margin", "gbm", "ensemble", "market"].map((k) => (
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
            <b className="text-ink">Elo</b> with a margin-of-victory multiplier (K = {ev.hyperparams.elo.k}, home advantage{" "}
            {ev.hyperparams.elo.home_adv} Elo points, {Math.round(ev.hyperparams.elo.season_regression * 100)}% pulled back to
            average each off-season). A <b className="text-ink">margin model</b> (ridge regression) predicts the final point
            margin from Elo, recent point differential, points scored and allowed, home/road form, season record and rest
            {sport === "nba" ? ", including back-to-backs" : " and quarterback changes"}; the margin becomes a win probability
            through a normal distribution. A matching model predicts total points.
          </p>
          <p>
            A <b className="text-ink">gradient-boosted classifier</b> uses the same inputs. The final probability averages the
            three with weights chosen on validation seasons; the projected score combines the predicted total and margin.
            Betting lines are never a model input. Model {perf.model.version}, trained {fmtDate(perf.model.trained_at)} on{" "}
            {perf.model.n_train.toLocaleString()} games.
          </p>
        </div>
      </Card>
    </div>
  );
}
