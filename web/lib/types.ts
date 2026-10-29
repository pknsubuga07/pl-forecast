export type Outcome = "H" | "D" | "A";
export type Probs = [number, number, number];

export interface Team {
  id: string;
  name: string;
  short: string;
  stadium: string | null;
  crest: string | null;
}

export interface FixtureSummary {
  match_id: string;
  gameweek: number;
  kickoff_utc: string;
  venue: string | null;
  home: Team;
  away: Team;
  p: Probs;
  predicted: Outcome;
  confidence: "high" | "medium" | "low";
  xg: [number, number];
  top_score: { score: string; p: number };
  market_p: Probs | null;
  market_source: string | null;
  disagreement: boolean;
  market_diff: Probs | null;
}

export interface Record3 {
  p: number;
  w: number;
  d: number;
  l: number;
  gf: number;
  ga: number;
  ppg: number | null;
  division?: string;
}

export interface Underlying {
  matches?: number;
  xg_for_pg?: number | null;
  xg_against_pg?: number | null;
  xg_matches?: number;
  shots_for_pg?: number | null;
  shots_against_pg?: number | null;
  sot_for_pg?: number | null;
  sot_against_pg?: number | null;
  clean_sheets?: number;
  goals_for_pg?: number;
  goals_against_pg?: number;
}

export interface FormItem {
  date: string;
  opponent: string;
  opponent_short: string;
  venue: "H" | "A";
  gf: number;
  ga: number;
  result: "W" | "D" | "L";
}

export interface SideContext {
  form: FormItem[];
  form_goals_for: number;
  form_goals_against: number;
  venue_record: { this_season: Record3; last_season: Record3 };
  underlying: Underlying;
  underlying_last5: Underlying;
  last_match: { kickoff_utc: string; competition: string; opponent: string; days: number } | null;
}

export interface TableRow {
  team_id: string;
  name: string;
  short: string;
  crest: string | null;
  position: number;
  played: number;
  won: number;
  drawn: number;
  lost: number;
  gf: number;
  ga: number;
  gd: number;
  points: number;
  deduction: number;
  ppg: number | null;
  form: ("W" | "D" | "L")[];
  xg_for: number | null;
  xg_against: number | null;
}

export interface Factor {
  group: string;
  effect: number;
  home_minus_away: number;
  favours: "home" | "away";
  text: string;
}

export interface FixtureDetail extends FixtureSummary {
  top_scores: { score: string; p: number }[];
  score_grid: number[][];
  components: Record<string, Probs>;
  weights: Record<string, number>;
  explanation: string;
  factors: Factor[];
  market: { source: string; label: string; fetched_at: string; odds: Probs; p: Probs; overround: number } | null;
  inputs: Record<string, number | null>;
  model_version: string;
  home_table: TableRow | null;
  away_table: TableRow | null;
  context: {
    home: SideContext;
    away: SideContext;
    h2h: {
      meetings: {
        date: string;
        season: string;
        division: string;
        home: string;
        away: string;
        home_goals: number;
        away_goals: number;
        result_for_home_team: "W" | "D" | "L";
      }[];
      home_wins: number;
      draws: number;
      away_wins: number;
    };
  };
}

export interface SourceStatus {
  source: string;
  last_ok_at: string | null;
  last_error: string | null;
  last_error_at: string | null;
}

export interface Meta {
  generated_at: string;
  season: string;
  next_gameweek: number | null;
  model_version: string;
  model_trained_at: string;
  n_train: number;
  sources: SourceStatus[];
  timezone: string;
  last_result_utc: string;
}

export interface Metrics {
  n: number;
  log_loss: number;
  brier: number;
  rps: number;
  accuracy: number;
}

export interface HistoryMatch {
  match_id: string;
  gameweek: number | null;
  kickoff_utc: string;
  home: string;
  away: string;
  home_short: string;
  away_short: string;
  home_crest: string | null;
  away_crest: string | null;
  home_goals: number;
  away_goals: number;
  result: Outcome;
  p: Probs;
  predicted: Outcome;
  correct: boolean;
  log_loss: number;
  mode: "live" | "backtest";
  model_version: string;
  predicted_at: string | null;
  market_p: Probs | null;
}

export type SummaryBlock = Metrics & { market?: Metrics; model_same_matches?: Metrics };

export interface History {
  season: string;
  matches: HistoryMatch[];
  summary: Partial<Record<"live" | "backtest" | "all", SummaryBlock>>;
}

export interface CalibrationBin {
  bin_lo: number;
  bin_hi: number;
  n: number;
  mean_pred: number;
  observed: number;
}

export interface EvalBlock {
  seasons: string[];
  n: number;
  metrics: Record<string, Metrics>;
  closing_subset: { n: number; metrics: Record<string, Metrics> };
}

export interface Performance {
  evaluation: {
    generated_at: string;
    labels: Record<string, string>;
    hyperparams: Record<string, unknown> & { ensemble_weights: Record<string, number> };
    blocks: { validation: EvalBlock; test: EvalBlock; current: EvalBlock };
    per_season: { season: string; n: number; metrics: Record<string, Metrics> }[];
    calibration_test: Record<string, CalibrationBin[]>;
  } | null;
  live: History["summary"];
  model: { version: string; trained_at: string; n_train: number; train_from: string; train_to: string };
}

export interface TeamPage extends Team {
  table: TableRow | null;
  elo_history: { date: string; elo: number; div: string }[];
  elo_now: number;
  form_trend: {
    date: string;
    opponent: string;
    venue: "H" | "A";
    gf: number;
    ga: number;
    result: "W" | "D" | "L";
    ppg5: number;
    xgf: number | null;
    xga: number | null;
    div: string;
  }[];
  upcoming: string[];
  home_record: Record3;
  away_record: Record3;
  underlying: Underlying;
}
