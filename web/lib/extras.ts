import "server-only";
import { existsSync, readFileSync } from "node:fs";
import path from "node:path";

export interface ParlayLeg {
  sport: "pl" | "nba" | "nfl";
  game_id: string;
  pick: string;
  label: string;
  matchup: string;
  kickoff_utc: string;
  p_model: number;
  p_market: number | null;
  odds: number;
  confidence: "high" | "medium" | "low";
  href: string;
}

export interface Parlay {
  parlay_id: string;
  day: string;
  tag: string;
  status: "open" | "won" | "lost" | "void";
  locked: string;
  first_kickoff: string;
  n_legs: number;
  p_model: number;
  p_market: number | null;
  odds: number;
  legs: ParlayLeg[];
}

export interface BTSummary { n: number; hit_rate: number; expected_hit_rate_model: number; expected_hit_rate_market: number; avg_odds: number; roi: number }

export interface ParlayData {
  generated_at: string;
  days: { day: string; n_games: number; n_eligible: number; parlays: Parlay[] }[];
  record: { n: number; won: number; hit_rate: number; expected_hit_rate: number; roi: number } | null;
  history: Parlay[];
  backtest: { days: number; seasons: string; all: BTSummary; by_legs: Record<string, BTSummary>; by_tag: Record<string, BTSummary> } | null;
}

export interface Prop {
  game_id: string;
  athlete_id: string;
  player: string | null;
  team: string | null;
  position: string | null;
  injury: string | null;
  market: string;
  label: string;
  line: number;
  projection: number;
  side: string;
  p_side: number;
  p_market: number | null;
  price: number | null;
  confidence: "high" | "medium" | "low";
  l5: number;
  l10: number;
  season_mean: number | null;
}

export interface PropMarketEval {
  label?: string;
  n_train: number;
  n_test: number;
  note?: string;
  mae_projection?: number | null;
  mae_line?: number;
  log_loss_model?: number;
  log_loss_market?: number;
  log_loss_market_with_margin?: number;
  hit_rate_all?: number;
  roi_all?: number;
  bets_confident?: number;
  hit_rate_confident?: number | null;
  roi_confident?: number | null;
  bets?: number;
  hit_rate?: number | null;
  roi?: number | null;
  assumed_prices?: boolean;
  over_rate_train?: number;
  log_loss_base_rate?: number;
}

export interface PropsData {
  sport: string;
  games: { game_id: string; kickoff_utc: string; home: { id: string; short: string; nickname: string; logo: string | null }; away: { id: string; short: string; nickname: string; logo: string | null }; props: Prop[] }[];
  record: { n: number; won: number; hit_rate: number; roi: number } | null;
  evaluation: { train_season: number; test_seasons: number[]; markets: Record<string, PropMarketEval> } | null;
}

const DIR = path.join(process.cwd(), "public", "data");

function load<T>(rel: string, fallback: T): T {
  const file = path.join(DIR, rel);
  return existsSync(file) ? (JSON.parse(readFileSync(file, "utf8")) as T) : fallback;
}

export const getParlays = () => load<ParlayData>("parlays.json", { generated_at: "", days: [], record: null, history: [], backtest: null });
export const getProps = (sport: string) => load<PropsData>(`${sport}/props.json`, { sport, games: [], record: null, evaluation: null });

export const americanToDecimal = (x: number) => (x < 0 ? 1 + 100 / -x : 1 + x / 100);
export const fmtAmerican = (x: number | null) => (x === null ? "–" : x > 0 ? `+${x}` : `${x}`);
export const SPORT_LABEL = { pl: "Premier League", nba: "NBA", nfl: "NFL" } as const;
