"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

const SPORTS = [
  { href: "/", label: "Premier League", match: (p: string) => !p.startsWith("/nba") && !p.startsWith("/nfl") },
  { href: "/nba", label: "NBA", match: (p: string) => p.startsWith("/nba") },
  { href: "/nfl", label: "NFL", match: (p: string) => p.startsWith("/nfl") },
];

export function SportTabs() {
  const path = usePathname();
  return (
    <nav aria-label="Sport" className="flex gap-1 overflow-x-auto text-sm">
      {SPORTS.map((s) => {
        const on = s.match(path);
        return (
          <Link
            key={s.href}
            href={s.href}
            aria-current={on ? "page" : undefined}
            className={`whitespace-nowrap rounded-full px-3 py-1 font-medium ${on ? "bg-ink text-bg" : "text-ink-2 hover:bg-surface-2"}`}
          >
            {s.label}
          </Link>
        );
      })}
    </nav>
  );
}

export function SectionNav({ items }: { items: { href: string; label: string }[] }) {
  const path = usePathname().replace(/\/$/, "") || "/";
  const active = (href: string) =>
    href === items[0].href ? path === href || path.startsWith(`${href === "/" ? "/match" : `${href}/game`}`) : path.startsWith(href);
  return (
    <nav aria-label="Section" className="-mx-1 flex gap-0.5 overflow-x-auto text-sm">
      {items.map((n) => (
        <Link
          key={n.href}
          href={n.href}
          aria-current={active(n.href) ? "page" : undefined}
          className={`whitespace-nowrap rounded-md px-2.5 py-1.5 ${active(n.href) ? "bg-surface-2 text-ink" : "text-ink-2 hover:bg-surface-2 hover:text-ink"}`}
        >
          {n.label}
        </Link>
      ))}
    </nav>
  );
}
