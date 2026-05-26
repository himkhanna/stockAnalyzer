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

export interface SearchHit {
  symbol: string;
  name: string;
  market: string;
  exchange: string;
  quote_type: string;
}

export interface SearchOut {
  query: string;
  hits: SearchHit[];
}

export interface WatchlistItem {
  ticker: string;
  market: string;
  note: string;
  date_added: string;
}

export interface WatchlistItemIn {
  ticker: string;
  market: string;
  note?: string;
}

export interface IndexSnapshot {
  symbol: string;
  name: string;
  market: string;
  price: number | null;
  change_pct: number | null;
  rsi: number | null;
  trend: string | null;
  score_label: SignalLabel | null;
  error: string | null;
}

export interface ConvictionRow {
  row: CardRow;
  direction: "bullish" | "bearish";
  rule_count: number;
  rule_notes: string[];
}

export interface SignalChange {
  symbol: string;
  market: string;
  previous_label: string;
  current_label: string;
  previous_value: number;
  current_value: number;
  captured_previous_at: string;
}

export interface EarningsItem {
  symbol: string;
  market: string;
  company: string | null;
  earnings_date: string;
  days_until: number;
}

export interface RiskTopWeight {
  symbol: string;
  market: string;
  weight_pct: number;
  market_value: number;
  currency_symbol: string;
}

export interface CurrencyExposure {
  currency: string;
  currency_symbol: string;
  market_value: number;
  pct_of_total_inr: number;
}

export interface RiskPanel {
  top_weights: RiskTopWeight[];
  currency_exposure: CurrencyExposure[];
  biggest_winners: CardRow[];
  biggest_losers: CardRow[];
}

export type AlertKind =
  | "price_above"
  | "price_below"
  | "rsi_above"
  | "rsi_below"
  | "score_at_or_above"
  | "score_at_or_below"
  | "score_flip_buy"
  | "score_flip_sell"
  | "pct_drop_day"
  | "pct_rise_day";

export interface AlertIn {
  ticker: string;
  market: string;
  kind: AlertKind;
  threshold: number;
  note?: string;
}

export interface Alert {
  id: number;
  ticker: string;
  market: string;
  kind: AlertKind;
  threshold: number;
  note: string | null;
  active: boolean;
  created_at: string;
  last_fired_at: string | null;
}

export interface AlertEvent {
  id: number;
  alert_id: number;
  ticker: string;
  market: string;
  kind: AlertKind;
  threshold: number;
  fired_at: string;
  triggered_value: number | null;
  message: string | null;
  acknowledged: boolean;
}

export interface BrokerStatus {
  broker: string;
  has_credentials: boolean;
  connected: boolean;
  session_expires_at: string | null;
  login_url: string | null;
  note: string;
}

export interface BrokerHoldingPreview {
  broker_stock_code: string;
  isin: string;
  company_name: string | null;
  exchange_code: string;
  quantity: number;
  average_price: number;
  current_price: number | null;
  resolved_ticker: string | null;
  resolved_market: string | null;
  resolution_source: string | null;
  action: "add" | "update" | "unchanged" | "unresolved";
  existing_shares: number | null;
  existing_cost_basis: number | null;
}

export interface SyncPreview {
  rows: BrokerHoldingPreview[];
  add_count: number;
  update_count: number;
  unchanged_count: number;
  unresolved_count: number;
}

export interface SyncApplyResult {
  upserted: number;
  unresolved: number;
  removed: number;
}

export interface Backtest {
  symbol: string;
  market: string;
  start_date: string;
  end_date: string;
  bars: number;

  strategy_return_pct: number;
  buy_and_hold_return_pct: number;
  edge_pct: number;
  beat_hold: boolean;

  max_drawdown_pct: number;
  n_trades: number;
  win_rate_pct: number | null;
  avg_holding_days: number | null;
  in_market_pct: number;

  transaction_cost_pct: number;
  score_threshold_enter: number;
  score_threshold_exit: number;
  sentiment_used: boolean;
}

export interface Insights {
  conviction: ConvictionRow[];
  watchlist: CardRow[];
  indices: IndexSnapshot[];
  risk: RiskPanel;
  signal_changes: SignalChange[];
  upcoming_earnings: EarningsItem[];
  generated_at: string;
  note: string;
}
