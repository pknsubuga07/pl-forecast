import { notFound } from "next/navigation";
import { SectionNav } from "@/components/SectionNav";
import { StatusBar } from "@/components/StatusBar";
import { isSport, SPORTS, usMeta } from "@/lib/us";

export const dynamicParams = false;

export function generateStaticParams() {
  return SPORTS.map((sport) => ({ sport }));
}

export default async function SportLayout({ children, params }: LayoutProps<"/[sport]">) {
  const { sport } = await params;
  if (!isSport(sport)) notFound();
  const meta = usMeta(sport);
  const nav = [
    { href: `/${sport}`, label: "Games" },
    { href: `/${sport}/standings`, label: "Standings" },
    { href: `/${sport}/history`, label: "History" },
    { href: `/${sport}/performance`, label: "Performance" },
    { href: `/${sport}/teams`, label: "Teams" },
  ];
  return (
    <>
      <div className="border-b border-line bg-surface">
        <div className="mx-auto max-w-6xl space-y-1.5 px-4 py-2">
          <SectionNav items={nav} />
          {meta && <StatusBar generatedAt={meta.generated_at} season={meta.season} model={meta.model_version} sources={meta.sources} />}
        </div>
      </div>
      <main className="mx-auto w-full max-w-6xl flex-1 px-4 py-6">
        {meta ? children : <p className="card p-6 text-sm text-muted">No data has been exported for this sport yet.</p>}
      </main>
    </>
  );
}
