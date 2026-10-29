"use client";

import {
  CartesianGrid,
  Line,
  LineChart,
  ReferenceLine,
  ResponsiveContainer,
  Scatter,
  ComposedChart,
  Tooltip,
  XAxis,
  YAxis,
  Legend,
} from "recharts";
import type { CalibrationBin } from "@/lib/types";

const AXIS = { stroke: "var(--muted)", fontSize: 11, tickLine: false, axisLine: { stroke: "var(--border)" } } as const;
const GRID = { stroke: "var(--grid)", strokeDasharray: "0", vertical: false } as const;

function Tip({ active, payload, label, fmt, labelFmt }: {
  active?: boolean;
  payload?: { name: string; value: number; color: string }[];
  label?: string | number;
  fmt: (v: number) => string;
  labelFmt?: (l: string | number) => string;
}) {
  if (!active || !payload?.length) return null;
  return (
    <div className="rounded-lg border border-line bg-surface px-3 py-2 text-xs shadow-lg">
      {label !== undefined && <div className="mb-1 text-muted">{labelFmt ? labelFmt(label) : label}</div>}
      {payload.map((p) => (
        <div key={p.name} className="flex items-center gap-2">
          <span className="h-0.5 w-3" style={{ background: p.color }} />
          <b className="tabular text-ink">{fmt(p.value)}</b>
          <span className="text-ink-2">{p.name}</span>
        </div>
      ))}
    </div>
  );
}

/** Reliability diagram: predicted probability vs observed frequency, pooled over all three outcomes. */
export function CalibrationChart({ model, market }: { model: CalibrationBin[]; market: CalibrationBin[] }) {
  const pts = (bins: CalibrationBin[]) => bins.filter((b) => b.n >= 20).map((b) => ({ x: b.mean_pred, y: b.observed, n: b.n }));
  return (
    <div className="h-72 w-full">
      <ResponsiveContainer>
        <ComposedChart margin={{ top: 8, right: 12, bottom: 20, left: 0 }}>
          <CartesianGrid {...GRID} vertical />
          <XAxis type="number" dataKey="x" domain={[0, 0.9]} ticks={[0, 0.2, 0.4, 0.6, 0.8]} tickFormatter={(v) => `${Math.round(v * 100)}%`} {...AXIS}
            label={{ value: "Predicted probability", position: "insideBottom", offset: -12, fill: "var(--muted)", fontSize: 11 }} />
          <YAxis type="number" dataKey="y" domain={[0, 0.9]} ticks={[0, 0.2, 0.4, 0.6, 0.8]} tickFormatter={(v) => `${Math.round(v * 100)}%`} {...AXIS} width={44} />
          <ReferenceLine segment={[{ x: 0, y: 0 }, { x: 0.9, y: 0.9 }]} stroke="var(--muted)" strokeDasharray="4 4" />
          <Tooltip cursor={false} content={({ active, payload }) => {
            if (!active || !payload?.length) return null;
            const d = payload[0].payload as { x: number; y: number; n: number };
            return (
              <div className="rounded-lg border border-line bg-surface px-3 py-2 text-xs shadow-lg">
                <div className="text-ink-2">{payload[0].name}</div>
                <div>Predicted <b className="tabular">{(d.x * 100).toFixed(1)}%</b></div>
                <div>Happened <b className="tabular">{(d.y * 100).toFixed(1)}%</b></div>
                <div className="text-muted">{d.n} forecasts</div>
              </div>
            );
          }} />
          <Legend verticalAlign="top" height={24} iconType="circle" wrapperStyle={{ fontSize: 12, color: "var(--text-2)" }} />
          <Scatter isAnimationActive={false} name="Model (ensemble)" data={pts(model)} fill="var(--home)" line={{ stroke: "var(--home)", strokeWidth: 2 }} shape="circle" />
          <Scatter isAnimationActive={false} name="Bookmakers" data={pts(market)} fill="var(--away)" line={{ stroke: "var(--away)", strokeWidth: 2 }} shape="diamond" />
        </ComposedChart>
      </ResponsiveContainer>
    </div>
  );
}

export function EloChart({ data }: { data: { date: string; elo: number; div: string }[] }) {
  const min = Math.floor(Math.min(...data.map((d) => d.elo)) / 25) * 25;
  const max = Math.ceil(Math.max(...data.map((d) => d.elo)) / 25) * 25;
  return (
    <div className="h-60 w-full">
      <ResponsiveContainer>
        <LineChart data={data} margin={{ top: 8, right: 12, bottom: 0, left: 0 }}>
          <CartesianGrid {...GRID} />
          <XAxis dataKey="date" {...AXIS} minTickGap={48} tickFormatter={(d: string) => d.slice(0, 7)} />
          <YAxis domain={[min, max]} {...AXIS} width={44} />
          <Tooltip cursor={{ stroke: "var(--muted)", strokeWidth: 1 }}
            content={(p) => <Tip {...(p as object)} fmt={(v) => v.toFixed(0)} labelFmt={(l) => String(l)} />} />
          <Line isAnimationActive={false} type="monotone" dataKey="elo" name="Elo rating" stroke="var(--accent)" strokeWidth={2} dot={false} activeDot={{ r: 4 }} />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}

export function FormChart({ data }: { data: { date: string; opponent: string; venue: string; gf: number; ga: number; result: string; ppg5: number }[] }) {
  const rows = data.map((d, i) => ({ ...d, i, label: `${d.date} ${d.venue === "H" ? "v" : "@"} ${d.opponent} ${d.gf}–${d.ga}` }));
  return (
    <div className="h-56 w-full">
      <ResponsiveContainer>
        <LineChart data={rows} margin={{ top: 8, right: 12, bottom: 0, left: 0 }}>
          <CartesianGrid {...GRID} />
          <XAxis dataKey="date" {...AXIS} minTickGap={40} tickFormatter={(d: string) => d.slice(5)} />
          <YAxis domain={[0, 3]} ticks={[0, 1, 2, 3]} {...AXIS} width={28} />
          <Tooltip cursor={{ stroke: "var(--muted)", strokeWidth: 1 }}
            content={({ active, payload }) => {
              if (!active || !payload?.length) return null;
              const d = payload[0].payload as (typeof rows)[number];
              return (
                <div className="rounded-lg border border-line bg-surface px-3 py-2 text-xs shadow-lg">
                  <div className="text-muted">{d.label}</div>
                  <div><b className="tabular">{d.ppg5.toFixed(2)}</b> <span className="text-ink-2">points per game, last 5</span></div>
                </div>
              );
            }} />
          <Line isAnimationActive={false} type="monotone" dataKey="ppg5" name="Points per game (rolling 5)" stroke="var(--home)" strokeWidth={2}
            dot={(props: { cx?: number; cy?: number; index?: number }) => {
              const r = rows[props.index ?? 0]?.result;
              const fill = r === "W" ? "var(--win)" : r === "L" ? "var(--loss)" : "var(--draw)";
              return <circle key={props.index} cx={props.cx} cy={props.cy} r={4} fill={fill} stroke="var(--surface)" strokeWidth={2} />;
            }} />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}

export function RunningLossChart({ data }: { data: { n: number; model: number; market: number | null }[] }) {
  return (
    <div className="h-60 w-full">
      <ResponsiveContainer>
        <LineChart data={data} margin={{ top: 8, right: 12, bottom: 16, left: 0 }}>
          <CartesianGrid {...GRID} />
          <XAxis dataKey="n" {...AXIS} minTickGap={24} label={{ value: "Matches", position: "insideBottom", offset: -8, fill: "var(--muted)", fontSize: 11 }} />
          <YAxis domain={["auto", "auto"]} {...AXIS} width={44} tickFormatter={(v: number) => v.toFixed(2)} />
          <Tooltip cursor={{ stroke: "var(--muted)", strokeWidth: 1 }}
            content={(p) => <Tip {...(p as object)} fmt={(v) => v.toFixed(3)} labelFmt={(l) => `After ${l} matches`} />} />
          <Legend verticalAlign="top" height={24} wrapperStyle={{ fontSize: 12, color: "var(--text-2)" }} />
          <Line isAnimationActive={false} type="monotone" dataKey="model" name="Model" stroke="var(--home)" strokeWidth={2} dot={false} />
          <Line isAnimationActive={false} type="monotone" dataKey="market" name="Bookmakers" stroke="var(--away)" strokeWidth={2} dot={false} connectNulls />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}
