import "server-only";
import { existsSync, readFileSync } from "node:fs";
import path from "node:path";
import type { CalibrationBin, SourceStatus } from "./types";

export type Sport = "nba" | "nfl";
export const SPORTS: Sport[] = ["nba", "nfl"];
export const SPORT_NAME: Record<Sport, string> = { nba: "NBA", nfl: "NFL" };

export interface USRecord { w: number; l: number; t: number; pct: number | null; pf_pg?: number | null; pa_pg?: number | null }

export interface USTeam {
  id: string;
  name: string;
  short: string;
  nickname: string;
  conference: string;
  division: string;
  logo: string | null;
}

export interface USGame {
  game_id: string;
  kickoff_utc: string;
  week: number | null;
  playoff: boolean;
  neutral: boolean;
  venue: string | null;
  home: USTeam & { record: USRecord & { conf_rank: number; streak: string | null } };
  away: USTeam & { record: USRecord & { conf_rank: number; streak: string | null } };
  p_home: number;
  predicted: "H" | "A";
  confidence: "high" | "medium" | "low";
  pred_home_score: number;
  pred_away_score: number;
  pred_margin: number;
  pred_total: number;
  market_p_home: number | null;
  market_spread_home: number | null;
  market_total: number | null;
  market_label: string | null;
  disagreement: boolean;
}

export interface USSide {
  form: { date: string; opponent: string; venue: "H" | "A"; pf: number; pa: number; result: "W" | "L" | "T" }[];
  season: USRecord;
  last10: USRecord;
  streak: string | null;
  venue_this: USRecord;
  venue_last: USRecord;
  margin_pg: number | null;
  last_game: { date: string; opponent: string; days: number } | null;
}

export interface USGameDetail extends USGame {
  components: Record<string, number>;
  weights: Record<string, number>;
  explanation: string;
  factors: { group: string; label: string; effect_home: number; favours: "home" | "away"; text: string }[];
  market: { source: string; label: string; home_ml: number; away_ml: number; p_home: number; spread_home: number | null; total: number | null; overround: number } | null;
  inputs: Record<string, number | null>;
  model_version: string;
  home_qb: string | null;
  away_qb: string | null;
  context: {
    home: USSide;
    away: USSide;
    h2h: {
      meetings: { date: string; season: string; home: string; away: string; home_score: number; away_score: number; result_for_home_team: "W" | "L" | "T"; playoff: boolean }[];
      home_wins: number;
      away_wins: number;
    };
  };
}

export interface USStanding extends USTeam, USRecord {
  played: number;
  diff: number;
  home: USRecord;
  away: USRecord;
  last10: USRecord;
  streak: string | null;
  elo: number;
  form: ("W" | "L" | "T")[];
  conf_rank: number;
}

export interface USMeta {
  sport: Sport;
  generated_at: string;
  season: string;
  model_version: string;
  model_trained_at: string;
  n_train: number;
  sources: SourceStatus[];
  n_upcoming: number;
}

export interface BinMetrics { n: number; log_loss: number; brier: number; accuracy: number }

export interface USHistoryGame {
  game_id: string;
  kickoff_utc: string;
  week: number | null;
  home: string;
  away: string;
  home_logo: string | null;
  away_logo: string | null;
  home_score: number;
  away_score: number;
  p_home: number;
  pred_margin: number;
  actual_margin: number;
  mode: "live" | "backtest";
  predicted_at: string | null;
  correct: boolean | null;
  market_p_home: number | null;
  log_loss: number | null;
}

export type USSummary = BinMetrics & { margin_mae: number; market?: BinMetrics; model_same_games?: BinMetrics };

export interface USHistory {
  season: string;
  games: USHistoryGame[];
  summary: Partial<Record<"live" | "backtest" | "all", USSummary>>;
}

export interface USEvalBlock {
  seasons: string[];
  n: number;
  market_coverage: number;
  metrics: Record<string, BinMetrics>;
  spread: { n: number; model_mae: number | null; market_mae: number | null };
  totals: { n: number; model_mae: number | null; market_mae: number | null };
}

export interface USPerformance {
  evaluation: {
    generated_at: string;
    labels: Record<string, string>;
    hyperparams: { elo: { k: number; home_adv: number; season_regression: number }; ridge_alpha: number; ensemble_weights: Record<string, number> };
    blocks: { validation: USEvalBlock; test: USEvalBlock; current?: USEvalBlock };
    per_season: ({ season: string } & USEvalBlock)[];
    calibration_test: Record<string, CalibrationBin[]>;
  } | null;
  live: USHistory["summary"];
  model: { version: string; trained_at: string; n_train: number };
}

export interface USTeamPage extends USTeam {
  standing: USStanding;
  elo_history: { date: string; elo: number }[];
  elo_now: number;
  trend: { date: string; opponent: string; venue: "H" | "A"; pf: number; pa: number; result: "W" | "L" | "T"; margin5: number }[];
  upcoming: string[];
}

const DIR = path.join(process.cwd(), "public", "data");
const cache = new Map<string, unknown>();

function load<T>(sport: Sport, name: string, fallback: T): T {
  const key = `${sport}/${name}`;
  if (!cache.has(key)) {
    const file = path.join(DIR, sport, name);
    cache.set(key, existsSync(file) ? JSON.parse(readFileSync(file, "utf8")) : fallback);
  }
  return cache.get(key) as T;
}

export const isSport = (s: string): s is Sport => (SPORTS as string[]).includes(s);
export const usMeta = (s: Sport) => load<USMeta | null>(s, "meta.json", null);
export const usGames = (s: Sport) => load<USGame[]>(s, "games.json", []);
export const usDetails = (s: Sport) => load<Record<string, USGameDetail>>(s, "game_details.json", {});
export const usStandings = (s: Sport) => load<USStanding[]>(s, "standings.json", []);
export const usTeams = (s: Sport) => load<Record<string, USTeamPage>>(s, "teams.json", {});
export const usHistory = (s: Sport) => load<USHistory>(s, "history.json", { season: "", games: [], summary: {} });
export const usPerformance = (s: Sport) => load<USPerformance>(s, "performance.json", { evaluation: null, live: {}, model: { version: "", trained_at: "", n_train: 0 } });

export function rec(r: USRecord | undefined | null): string {
  if (!r) return "–";
  return r.t ? `${r.w}-${r.l}-${r.t}` : `${r.w}-${r.l}`;
}

export function spreadText(homeSpread: number | null, home: string, away: string): string {
  if (homeSpread === null || homeSpread === undefined) return "–";
  if (homeSpread === 0) return "Pick'em";
  return homeSpread < 0 ? `${home} ${homeSpread.toFixed(1)}` : `${away} ${(-homeSpread).toFixed(1)}`;
}

export function modelSpread(margin: number, home: string, away: string): string {
  if (Math.abs(margin) < 0.25) return "Pick'em";
  return margin > 0 ? `${home} -${margin.toFixed(1)}` : `${away} -${(-margin).toFixed(1)}`;
}
