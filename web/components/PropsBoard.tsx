"use client";

import { useMemo, useState } from "react";
import type { Prop, PropsData } from "@/lib/extras";
import { ConfidenceBadge } from "./ui";
import { Logo } from "./us-ui";

type Game = PropsData["games"][number] & { time: string };

const am = (x: number | null) => (x === null ? "–" : x > 0 ? `+${x}` : `${x}`);

export function PropsBoard({ games, markets }: { games: Game[]; markets: { id: string; label: string }[] }) {
  const [market, setMarket] = useState("all");
  const [minConf, setMinConf] = useState<"medium" | "all">("medium");
  const [game, setGame] = useState("all");
  const keep = (p: Prop) => (market === "all" || p.market === market) && (minConf === "all" || p.confidence !== "low");
  const shown = useMemo(
    () => games.filter((g) => game === "all" || g.game_id === game).map((g) => ({ ...g, props: g.props.filter(keep) })).filter((g) => g.props.length),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [games, market, minConf, game],
  );
  return (
    <div>
      <div className="mb-4 flex flex-wrap items-center gap-2">
        <select aria-label="Market" value={market} onChange={(e) => setMarket(e.target.value)} className="rounded-lg border border-line bg-surface px-3 py-1.5 text-sm">
          <option value="all">All markets</option>
          {markets.map((m) => <option key={m.id} value={m.id}>{m.label}</option>)}
        </select>
        <select aria-label="Game" value={game} onChange={(e) => setGame(e.target.value)} className="rounded-lg border border-line bg-surface px-3 py-1.5 text-sm">
          <option value="all">All games</option>
          {games.map((g) => <option key={g.game_id} value={g.game_id}>{g.away.short} @ {g.home.short} · {g.time}</option>)}
        </select>
        <div role="group" aria-label="Confidence" className="flex overflow-hidden rounded-lg border border-line bg-surface text-sm">
          {(["medium", "all"] as const).map((c) => (
            <button key={c} type="button" aria-pressed={minConf === c} onClick={() => setMinConf(c)}
              className={`px-3 py-1.5 ${minConf === c ? "bg-ink text-bg" : "text-ink-2 hover:bg-surface-2"}`}>
              {c === "medium" ? "Medium + high only" : "All"}
            </button>
          ))}
        </div>
        <span className="ml-auto text-xs text-muted">{shown.reduce((a, g) => a + g.props.length, 0)} props</span>
      </div>
      {shown.length === 0 && <p className="card p-6 text-sm text-muted">No props match these filters yet. Lines usually appear the day before the game.</p>}
      <div className="space-y-5">
        {shown.map((g) => (
          <section key={g.game_id} className="card p-4">
            <h2 className="mb-3 flex items-center gap-2 text-sm font-semibold">
              <Logo src={g.away.logo} alt={g.away.short} size={20} /> {g.away.nickname} @ {g.home.nickname}
              <Logo src={g.home.logo} alt={g.home.short} size={20} />
              <span className="font-normal text-muted">· {g.time}</span>
            </h2>
            <div className="overflow-x-auto">
              <table className="w-full min-w-[44rem] text-sm tabular">
                <thead><tr className="text-left text-xs text-muted">
                  <th className="pb-2 font-normal">Player</th><th className="pb-2 font-normal">Market</th>
                  <th className="pb-2 text-right font-normal">Line</th><th className="pb-2 text-right font-normal">Projection</th>
                  <th className="pb-2 text-right font-normal">Last 5 / 10</th><th className="pb-2 pl-3 font-normal">Lean</th>
                  <th className="pb-2 text-right font-normal">Model</th><th className="pb-2 text-right font-normal">Market</th>
                  <th className="pb-2 text-right font-normal">Price</th><th className="pb-2 pl-3 font-normal">Confidence</th>
                </tr></thead>
                <tbody>
                  {g.props.map((p) => (
                    <tr key={`${p.athlete_id}-${p.market}`} className="border-t border-line">
                      <td className="py-1.5 pr-2">
                        <span className="font-medium">{p.player ?? "Unknown"}</span>
                        <span className="ml-1 text-xs text-muted">{p.team}{p.position ? ` · ${p.position}` : ""}</span>
                        {p.injury && <span className="ml-1 rounded bg-warn/15 px-1 text-[10px] text-warn">{p.injury}</span>}
                      </td>
                      <td className="py-1.5 pr-2 text-ink-2">{p.label}</td>
                      <td className="py-1.5 text-right">{p.market === "anytime_td" ? "1+" : p.line}</td>
                      <td className="py-1.5 text-right font-medium">{p.market === "anytime_td" ? `${p.projection.toFixed(2)} TD` : p.projection.toFixed(1)}</td>
                      <td className="py-1.5 text-right text-ink-2">{p.l5} / {p.l10}</td>
                      <td className={`py-1.5 pl-3 font-semibold ${p.side === "Under" ? "text-away" : "text-home"}`}>{p.side}</td>
                      <td className="py-1.5 text-right">{Math.round(p.p_side * 100)}%</td>
                      <td className="py-1.5 text-right text-ink-2">{p.p_market === null ? "–" : `${Math.round(p.p_market * 100)}%`}</td>
                      <td className="py-1.5 text-right text-ink-2">{am(p.price)}</td>
                      <td className="py-1.5 pl-3"><ConfidenceBadge level={p.confidence} short /></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>
        ))}
      </div>
    </div>
  );
}
