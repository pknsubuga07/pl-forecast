import type { Metadata } from "next";
import Link from "next/link";
import { Card, Crest, ResultPill } from "@/components/ui";
import { getMeta, getTable } from "@/lib/data";
import { num } from "@/lib/format";

export const metadata: Metadata = { title: "League table" };

export default function TablePage() {
  const table = getTable();
  const meta = getMeta();
  return (
    <div className="space-y-5">
      <h1 className="text-2xl font-semibold tracking-tight">Premier League table · {meta.season}</h1>
      <Card>
        <div className="overflow-x-auto">
          <table className="w-full min-w-[44rem] text-sm tabular">
            <thead>
              <tr className="text-right text-xs text-muted">
                <th className="pb-2 text-left font-normal">#</th>
                <th className="pb-2 text-left font-normal">Club</th>
                <th className="pb-2 font-normal">P</th><th className="pb-2 font-normal">W</th><th className="pb-2 font-normal">D</th><th className="pb-2 font-normal">L</th>
                <th className="pb-2 font-normal">GF</th><th className="pb-2 font-normal">GA</th><th className="pb-2 font-normal">GD</th>
                <th className="pb-2 font-normal">Pts</th><th className="pb-2 font-normal">PPG</th>
                <th className="pb-2 font-normal">xG for</th><th className="pb-2 font-normal">xG agst</th>
                <th className="pb-2 pl-3 text-left font-normal">Last 5</th>
              </tr>
            </thead>
            <tbody>
              {table.map((r) => (
                <tr key={r.team_id} className="border-t border-line text-right">
                  <td className="py-2 text-left text-muted">{r.position}</td>
                  <td className="py-2 text-left">
                    <Link href={`/teams/${r.team_id}`} className="flex items-center gap-2 hover:underline">
                      <Crest team={r} size={20} />
                      <span className="whitespace-nowrap font-medium">{r.name}</span>
                    </Link>
                  </td>
                  <td>{r.played}</td><td>{r.won}</td><td>{r.drawn}</td><td>{r.lost}</td>
                  <td>{r.gf}</td><td>{r.ga}</td><td>{r.gd > 0 ? `+${r.gd}` : r.gd}</td>
                  <td className="font-semibold">{r.points}{r.deduction ? <sup className="text-loss">*</sup> : null}</td>
                  <td className="text-ink-2">{num(r.ppg, 2)}</td>
                  <td className="text-ink-2">{num(r.xg_for, 1)}</td>
                  <td className="text-ink-2">{num(r.xg_against, 1)}</td>
                  <td className="py-2 pl-3"><div className="flex gap-1">{r.form.map((f, i) => <ResultPill key={i} r={f} />)}</div></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="mt-3 text-xs text-muted">
          Computed from match results (football-data.co.uk, with FPL scores filling the gap until football-data updates).
          Ties are broken by goal difference, then goals scored. * includes a points deduction.
        </p>
      </Card>
    </div>
  );
}
