import { SectionNav } from "@/components/SectionNav";
import { StatusBar } from "@/components/StatusBar";
import { getMeta } from "@/lib/data";

const NAV = [
  { href: "/", label: "Fixtures" },
  { href: "/table", label: "Table" },
  { href: "/history", label: "History" },
  { href: "/performance", label: "Performance" },
  { href: "/teams", label: "Teams" },
];

export default function PLLayout({ children }: { children: React.ReactNode }) {
  const meta = getMeta();
  return (
    <>
      <div className="border-b border-line bg-surface">
        <div className="mx-auto max-w-6xl space-y-1.5 px-4 py-2">
          <SectionNav items={NAV} />
          <StatusBar generatedAt={meta.generated_at} season={meta.season} model={meta.model_version} sources={meta.sources} />
        </div>
      </div>
      <main className="mx-auto w-full max-w-6xl flex-1 px-4 py-6">{children}</main>
    </>
  );
}
