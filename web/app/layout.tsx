import type { Metadata, Viewport } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import Link from "next/link";
import { SportTabs } from "@/components/SectionNav";
import { ThemeToggle } from "@/components/ThemeToggle";
import "./globals.css";

const geistSans = Geist({ variable: "--font-geist-sans", subsets: ["latin"] });
const geistMono = Geist_Mono({ variable: "--font-geist-mono", subsets: ["latin"] });

export const metadata: Metadata = {
  title: { default: "Forecast", template: "%s · Forecast" },
  description: "Premier League, NBA and NFL win probabilities from Elo, goals/margin and gradient-boosting models, compared with bookmaker odds.",
};

export const viewport: Viewport = {
  themeColor: [
    { media: "(prefers-color-scheme: light)", color: "#f6f6f4" },
    { media: "(prefers-color-scheme: dark)", color: "#111110" },
  ],
};

// Runs before first paint so the page never flashes the wrong theme.
const themeScript = `(function(){try{var t=localStorage.getItem('theme');if(t!=='light'&&t!=='dark'){t=matchMedia('(prefers-color-scheme: dark)').matches?'dark':'light'}document.documentElement.setAttribute('data-theme',t)}catch(e){}})()`;

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="en" suppressHydrationWarning className={`${geistSans.variable} ${geistMono.variable} h-full antialiased`}>
      <head>
        <script dangerouslySetInnerHTML={{ __html: themeScript }} />
      </head>
      <body className="min-h-full flex flex-col">
        <header className="sticky top-0 z-20 border-b border-line bg-bg/85 backdrop-blur">
          <div className="mx-auto flex max-w-6xl items-center gap-3 px-4 py-2.5">
            <Link href="/" className="flex items-center gap-2 font-semibold tracking-tight">
              <span aria-hidden className="grid h-7 w-7 place-items-center rounded-lg bg-accent text-[13px] font-bold text-white">F</span>
              <span className="hidden sm:inline">Forecast</span>
            </Link>
            <SportTabs />
            <span className="flex-1" />
            <ThemeToggle />
          </div>
        </header>
        {children}
        <footer className="border-t border-line">
          <div className="mx-auto max-w-6xl space-y-2 px-4 py-6 text-xs text-muted">
            <p className="font-medium text-ink-2">
              For personal and educational use only. This is not betting advice and not a betting tool.
            </p>
            <p>
              Premier League data: football-data.co.uk (results, match stats, odds, 2026-27 xG), Fantasy Premier League API
              (fixtures, kickoff times). NFL data: nflverse (games, lines, starting QBs). NBA data and venues, cup and
              European fixtures, DraftKings odds and team logos: ESPN. Crests and logos © their clubs and leagues. Times
              shown in New York time (ET).
            </p>
          </div>
        </footer>
      </body>
    </html>
  );
}
