import type { Metadata } from "next";
import Link from "next/link";
import { Card } from "@/components/ui";
import { Logo, WLPill } from "@/components/us-ui";
import { isSport, rec, SPORT_NAME, usMeta, usStandings, type Sport, type USStanding } from "@/lib/us";

export async function generateMetadata({ params }: PageProps<"/[sport]/standings">): Promise<Metadata> {
  const { sport } = await params;
  return { title: `${SPORT_NAME[sport as Sport] ?? ""} standings` };
}

export default async function StandingsPage({ params }: PageProps<"/[sport]/standings">) {
  const { sport } = await params;
  if (!isSport(sport)) return null;
  const rows = usStandings(sport);
  const meta = usMeta(sport);
  const groups = sport === "nfl" ? [...new Set(rows.map((r) => r.division))].sort() : ["East", "West"];
  const key = (r: USStanding) => (sport === "nfl" ? r.division : r.conference);
  return (
    <div className="space-y-5">
      <h1 className="text-2xl font-semibold tracking-tight">{SPORT_NAME[sport]} standings · {meta?.season}</h1>
      <div className={`grid gap-5 ${sport === "nfl" ? "lg:grid-cols-2" : ""}`}>
        {groups.map((gname) => (
          <Card key={gname} title={sport === "nfl" ? gname : `${gname}ern Conference`}>
            <div className="overflow-x-auto">
              <table className="w-full min-w-[36rem] text-sm tabular">
                <thead>
                  <tr className="text-right text-xs text-muted">
                    <th className="pb-2 text-left font-normal">Team</th>
                    <th className="pb-2 font-normal">W-L</th><th className="pb-2 font-normal">Pct</th>
                    <th className="pb-2 font-normal">PF/g</th><th className="pb-2 font-normal">PA/g</th><th className="pb-2 font-normal">Diff</th>
                    <th className="pb-2 font-normal">Home</th><th className="pb-2 font-normal">Away</th>
                    <th className="pb-2 font-normal">Elo</th><th className="pb-2 pl-3 text-left font-normal">Last 5</th>
                  </tr>
                </thead>
                <tbody>
                  {rows.filter((r) => key(r) === gname).map((r, i) => (
                    <tr key={r.id} className="border-t border-line text-right">
                      <td className="py-2 text-left">
                        <Link href={`/${sport}/teams/${r.id}`} className="flex items-center gap-2 hover:underline">
                          <span className="w-4 text-xs text-muted">{i + 1}</span>
                          <Logo src={r.logo} alt={r.short} size={20} />
                          <span className="whitespace-nowrap font-medium">{r.nickname}</span>
                        </Link>
                      </td>
                      <td className="font-semibold">{rec(r)}</td>
                      <td className="text-ink-2">{r.pct === null ? "–" : r.pct.toFixed(3).replace(/^0/, "")}</td>
                      <td className="text-ink-2">{r.pf_pg ?? "–"}</td>
                      <td className="text-ink-2">{r.pa_pg ?? "–"}</td>
                      <td>{r.diff > 0 ? `+${r.diff}` : r.diff}</td>
                      <td className="text-ink-2">{rec(r.home)}</td>
                      <td className="text-ink-2">{rec(r.away)}</td>
                      <td className="text-ink-2">{r.elo.toFixed(0)}</td>
                      <td className="py-2 pl-3"><div className="flex gap-1">{r.form.map((f, j) => <WLPill key={j} r={f} />)}</div></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Card>
        ))}
      </div>
      <p className="text-xs text-muted">Regular season only, computed from game results; ordered by win percentage, then point differential (not the league&apos;s official tie-breakers).</p>
    </div>
  );
}
