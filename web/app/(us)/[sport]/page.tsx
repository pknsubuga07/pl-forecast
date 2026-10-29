import type { Metadata } from "next";
import { USGameList, type USGameRow } from "@/components/USGameList";
import { dayKey, fmtDay, fmtTime } from "@/lib/format";
import { isSport, modelSpread, SPORT_NAME, spreadText, usGames, usStandings, type Sport } from "@/lib/us";

export async function generateMetadata({ params }: PageProps<"/[sport]">): Promise<Metadata> {
  const { sport } = await params;
  return { title: `${SPORT_NAME[sport as Sport] ?? ""} games` };
}

const shortDay = new Intl.DateTimeFormat("en-US", { timeZone: "America/New_York", weekday: "short", month: "short", day: "numeric" });

export default async function GamesPage({ params }: PageProps<"/[sport]">) {
  const { sport } = await params;
  if (!isSport(sport)) return null;
  const games: USGameRow[] = usGames(sport).map((g) => ({
    ...g,
    day: fmtDay(g.kickoff_utc),
    dayKey: dayKey(g.kickoff_utc),
    time: fmtTime(g.kickoff_utc),
    group: sport === "nfl" ? (g.playoff ? "Playoffs" : `Week ${g.week}`) : shortDay.format(new Date(g.kickoff_utc)),
    spreadModel: modelSpread(g.pred_margin, g.home.short, g.away.short),
    spreadMarket: spreadText(g.market_spread_home, g.home.short, g.away.short),
  }));
  const teams = usStandings(sport).map((t) => ({ id: t.id, name: t.name })).sort((a, b) => a.name.localeCompare(b.name));
  const gaps = games.filter((g) => g.disagreement).length;
  return (
    <div>
      <div className="mb-6 flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Upcoming {SPORT_NAME[sport]} games</h1>
          <p className="mt-1 max-w-2xl text-sm text-ink-2">
            Win probabilities, projected scores and the model&apos;s spread and total for the next{" "}
            {sport === "nfl" ? "two weeks" : "seven days"}, next to the betting line. Select a game for the full breakdown.
            Times are New York time.
            {gaps > 0 && ` ${gaps} games differ from the moneyline by 10+ points.`}
          </p>
        </div>
        <div className="flex items-center gap-3 text-xs text-ink-2">
          <span className="flex items-center gap-1.5"><span className="h-2.5 w-2.5 rounded-[3px] bg-away" />Away win</span>
          <span className="flex items-center gap-1.5"><span className="h-2.5 w-2.5 rounded-[3px] bg-home" />Home win</span>
        </div>
      </div>
      {games.length === 0 ? (
        <p className="card p-6 text-sm text-muted">No games scheduled in the next few days (off-season or break).</p>
      ) : (
        <USGameList sport={sport} games={games} teams={teams} />
      )}
    </div>
  );
}
