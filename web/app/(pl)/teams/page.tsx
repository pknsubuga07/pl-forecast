import type { Metadata } from "next";
import Link from "next/link";
import { Crest } from "@/components/ui";
import { getTeams } from "@/lib/data";

export const metadata: Metadata = { title: "Teams" };

export default function TeamsPage() {
  const teams = Object.values(getTeams()).sort((a, b) => a.name.localeCompare(b.name));
  return (
    <div>
      <h1 className="mb-5 text-2xl font-semibold tracking-tight">Teams</h1>
      <ul className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4">
        {teams.map((t) => (
          <li key={t.id}>
            <Link href={`/teams/${t.id}`} className="card flex items-center gap-3 p-3 hover:border-[var(--accent)]">
              <Crest team={t} size={36} />
              <div className="min-w-0">
                <div className="truncate font-medium">{t.name}</div>
                <div className="text-xs text-muted tabular">
                  {t.table ? `${t.table.position}. · ${t.table.points} pts` : ""} · Elo {t.elo_now.toFixed(0)}
                </div>
              </div>
            </Link>
          </li>
        ))}
      </ul>
    </div>
  );
}
