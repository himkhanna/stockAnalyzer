// Wire types — mirror web/api/schemas.py.
// Keep in sync; consider auto-generating from OpenAPI later.

export type SignalLabel =
  | "Strong Sell"
  | "Sell"
  | "Hold"
  | "Buy"
  | "Strong Buy";

export interface TradeSetup {
  valid: boolean;
  entry?: number | null;
  stop?: number | null;
  target?: number | null;
  risk_reward?: number | null;
}

export interface CardRow {
  symbol: string;
  market: string;
  currency: string;
  currency_symbol: string;
  price?: number | null;
  change_pct?: number | null;
  stale: boolean;
  score_value?: number | null;
  score_label?: SignalLabel | null;
  rsi?: number | null;
  trend?: string | null;
  sentiment_label?: string | null;
  sentiment_total: number;
  setup: TradeSetup;
  recent_closes: number[];

  shares?: number | null;
  cost_basis?: number | null;
  market_value?: number | null;
  pnl?: number | null;
  pnl_pct?: number | null;
  weight_pct?: number | null;
  overweight: boolean;

  has_digest: boolean;
  error?: string | null;
}

export interface CurrencyBucket {
  currency: string;
  currency_symbol: string;
  market_value: number;
  cost_total: number;
  pnl: number;
  pnl_pct: number;
  n_positions: number;
}

export interface Dashboard {
  rows: CardRow[];
  buckets: CurrencyBucket[];
  signal_counts: Record<string, number>;
  overweight_count: number;
  winners_count: number;
  losers_count: number;
  loaded_at: string;
}

export interface Holding {
  ticker: string;
  market: string;
  shares: number;
  cost_basis: number;
  currency: string;
  date_added: string; // YYYY-MM-DD
}

export interface HoldingIn {
  ticker: string;
  market: string;
  shares: number;
  cost_basis: number;
  date_added?: string;
}

export interface ImportErrorRow {
  reason: string;
  isin?: string | null;
  name?: string | null;
  broker_symbol?: string | null;
}

export interface ImportResult {
  imported: number;
  errors: ImportErrorRow[];
}

export interface DigestPayload {
  symbol: string;
  market: string;
  markdown: string;
  has_synthesis: boolean;
  generated_at?: string;
}

export interface Lookup {
  row: CardRow;
  markdown?: string | null;
}
