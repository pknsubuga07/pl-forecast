import type { Metadata, Viewport } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import Link from "next/link";
import { ThemeToggle } from "@/components/ThemeToggle";
import { getMeta } from "@/lib/data";
import { fmtUpdated } from "@/lib/format";
import "./globals.css";

const geistSans = Geist({ variable: "--font-geist-sans", subsets: ["latin"] });
const geistMono = Geist_Mono({ variable: "--font-geist-mono", subsets: ["latin"] });

export const metadata: Metadata = {
  title: { default: "PL Forecast", template: "%s · PL Forecast" },
  description: "Premier League match probabilities from an Elo, Dixon-Coles and gradient-boosting model, compared with bookmaker odds.",
};

export const viewport: Viewport = {
  themeColor: [
    { media: "(prefers-color-scheme: light)", color: "#f6f6f4" },
    { media: "(prefers-color-scheme: dark)", color: "#111110" },
  ],
};

// Runs before first paint so the page never flashes the wrong theme.
const themeScript = `(function(){try{var t=localStorage.getItem('theme');if(t!=='light'&&t!=='dark'){t=matchMedia('(prefers-color-scheme: dark)').matches?'dark':'light'}document.documentElement.setAttribute('data-theme',t)}catch(e){}})()`;

const NAV = [
  { href: "/", label: "Fixtures" },
  { href: "/table", label: "Table" },
  { href: "/history", label: "History" },
  { href: "/performance", label: "Performance" },
  { href: "/teams", label: "Teams" },
];

export default function RootLayout({ children }: LayoutProps<"/">) {
  const meta = getMeta();
  const failing = meta.sources.filter((s) => s.last_error_at && (!s.last_ok_at || s.last_error_at > s.last_ok_at));
  return (
    <html lang="en" suppressHydrationWarning className={`${geistSans.variable} ${geistMono.variable} h-full antialiased`}>
      <head>
        <script dangerouslySetInnerHTML={{ __html: themeScript }} />
      </head>
      <body className="min-h-full flex flex-col">
        <header className="sticky top-0 z-20 border-b border-line bg-bg/85 backdrop-blur">
          <div className="mx-auto flex max-w-6xl items-center gap-3 px-4 py-3">
            <Link href="/" className="flex items-center gap-2 font-semibold tracking-tight">
              <span aria-hidden className="grid h-7 w-7 place-items-center rounded-lg bg-accent text-[13px] font-bold text-white">PL</span>
              <span className="hidden sm:inline">PL Forecast</span>
            </Link>
            <nav aria-label="Main" className="-mx-1 flex flex-1 gap-0.5 overflow-x-auto text-sm">
              {NAV.map((n) => (
                <Link key={n.href} href={n.href} className="whitespace-nowrap rounded-md px-2.5 py-1.5 text-ink-2 hover:bg-surface-2 hover:text-ink">
                  {n.label}
                </Link>
              ))}
            </nav>
            <ThemeToggle />
          </div>
        </header>
        <div className="border-b border-line bg-surface">
          <div className="mx-auto flex max-w-6xl flex-wrap items-center gap-x-4 gap-y-1 px-4 py-1.5 text-xs text-muted">
            <span>
              Data last updated <time dateTime={meta.generated_at} className="font-medium text-ink-2">{fmtUpdated(meta.generated_at)}</time>
            </span>
            <span>Season {meta.season}</span>
            <span>Model {meta.model_version}</span>
            {failing.length > 0 && (
              <span className="text-warn" role="status">
                ⚠ Source issue: {failing.map((s) => s.source).join(", ")} – showing last good data
              </span>
            )}
          </div>
        </div>
        <main className="mx-auto w-full max-w-6xl flex-1 px-4 py-6">{children}</main>
        <footer className="border-t border-line">
          <div className="mx-auto max-w-6xl space-y-2 px-4 py-6 text-xs text-muted">
            <p className="font-medium text-ink-2">
              For personal and educational use only. This is not betting advice and not a betting tool.
            </p>
            <p>
              Data: football-data.co.uk (results, match stats, odds, 2026-27 xG), Fantasy Premier League API (fixtures,
              kickoff times), ESPN (venues, cup and European fixtures, DraftKings odds). Crests © their clubs, via
              premierleague.com. Times shown in New York time (ET).
            </p>
          </div>
        </footer>
      </body>
    </html>
  );
}
