import type { Metadata } from "next";
import Link from "next/link";
import { Logo } from "@/components/us-ui";
import { isSport, rec, SPORT_NAME, usTeams, type Sport } from "@/lib/us";

export async function generateMetadata({ params }: PageProps<"/[sport]/teams">): Promise<Metadata> {
  const { sport } = await params;
  return { title: `${SPORT_NAME[sport as Sport] ?? ""} teams` };
}

export default async function USTeamsPage({ params }: PageProps<"/[sport]/teams">) {
  const { sport } = await params;
  if (!isSport(sport)) return null;
  const teams = Object.values(usTeams(sport)).sort((a, b) => a.name.localeCompare(b.name));
  return (
    <div>
      <h1 className="mb-5 text-2xl font-semibold tracking-tight">{SPORT_NAME[sport]} teams</h1>
      <ul className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4">
        {teams.map((t) => (
          <li key={t.id}>
            <Link href={`/${sport}/teams/${t.id}`} className="card flex items-center gap-3 p-3 hover:border-[var(--accent)]">
              <Logo src={t.logo} alt={t.short} size={36} />
              <div className="min-w-0">
                <div className="truncate font-medium">{t.name}</div>
                <div className="text-xs text-muted tabular">{rec(t.standing)} · Elo {t.elo_now.toFixed(0)}</div>
              </div>
            </Link>
          </li>
        ))}
      </ul>
    </div>
  );
}
