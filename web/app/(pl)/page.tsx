import { FixtureList, type FixtureRow } from "@/components/FixtureList";
import { OutcomeLegend } from "@/components/ui";
import { getFixtures, getMeta, getTable } from "@/lib/data";
import { dayKey, fmtDay, fmtTime } from "@/lib/format";

export default function FixturesPage() {
  const meta = getMeta();
  const fixtures: FixtureRow[] = getFixtures().map((f) => ({
    ...f,
    day: fmtDay(f.kickoff_utc),
    dayKey: dayKey(f.kickoff_utc),
    time: fmtTime(f.kickoff_utc),
  }));
  const teams = getTable()
    .map((t) => ({ id: t.team_id, name: t.name }))
    .sort((a, b) => a.name.localeCompare(b.name));
  const disagreements = fixtures.filter((f) => f.disagreement).length;

  return (
    <div>
      <div className="mb-6 flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Upcoming fixtures</h1>
          <p className="mt-1 max-w-2xl text-sm text-ink-2">
            Home win, draw and away win probabilities for the next {new Set(fixtures.map((f) => f.gameweek)).size} gameweeks
            {meta.next_gameweek ? ` from GW${meta.next_gameweek}` : ""}. Select a match for the full breakdown. Kickoff
            times are New York time.
            {disagreements > 0 && ` ${disagreements} fixtures differ from the bookmakers by 10+ points on some outcome.`}
          </p>
        </div>
        <OutcomeLegend />
      </div>
      {fixtures.length === 0 ? (
        <p className="card p-6 text-sm text-muted">
          No upcoming fixtures are scheduled right now (off-season or international break). Predictions appear here as
          soon as the fixture list is published.
        </p>
      ) : (
        <FixtureList fixtures={fixtures} teams={teams} />
      )}
    </div>
  );
}
