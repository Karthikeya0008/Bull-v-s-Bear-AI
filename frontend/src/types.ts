export type Status = "upcoming" | "open" | "listed";

export interface Ipo {
  ipo_id: string;
  company: string;
  status: Status;
  sector: string | null;
  exchanges: string | null;
  price_band_low: number | null;
  price_band_high: number | null;
  lot_size: number | null;
  issue_open: string | null;
  issue_close: string | null;
  listing_date: string | null;
  fresh_issue_cr: number | null;
  ofs_cr: number | null;
  nse_symbol: string | null;
  source: string;
  chunks: number;
  debates: number;
  documents?: DocumentInfo[];
}

export interface DocumentInfo {
  doc_id: string;
  doc_type: string;
  filed_date: string | null;
  source_url: string | null;
  pages: number | null;
  chunks: number | null;
  table_rows: number | null;
  status: string;
}

export interface MetricInput {
  value: number | null;
  page: number | null;
  line_item?: string;
  period?: string;
  raw_label?: string;
  source?: string;
}

export interface Metric {
  metric_id: string;
  name: string;
  label: string;
  period: string;
  value: number | null;
  unit: string;
  formula: string;
  inputs: Record<string, MetricInput>;
  source_pages: number[];
  status: "ok" | "skipped";
  note: string | null;
  doc_id: string | null;
}

export type Side = "bull" | "bear";

export interface Claim {
  claim_id: string;
  round: number;
  stance: Side;
  text: string;
  evidence: string[];
  strength: number;
  quote: string;
  rebuts: string | null;
}

export interface Verification {
  claim_id: string;
  status: "supported" | "partially_supported" | "struck";
  reason: string;
  entailment: number | null;
  method: string;
  valid_refs: string[];
  invalid_refs: string[];
  unmatched_figures: string[];
}

export interface Verdict {
  verdict: string;
  confidence: string;
  confidence_score: number;
  rationale: string;
  decisive_bull: string[];
  decisive_bear: string[];
  method: string;
  model: string;
  struck: number;
  total_claims: number;
  disclaimer: string;
  scores?: { bull: number; bear: number };
}

export interface ChunkDetail {
  chunk_id: string;
  doc_id: string;
  doc_type: string;
  section: string;
  page: number;
  page_end: number;
  text: string;
  source_url: string | null;
  pdf_url: string;
}

export interface DebateEvent {
  type: string;
  debate_id: string;
  [key: string]: unknown;
}

export interface DebateSummary {
  debate_id: string;
  status: string;
  verdict: string | null;
  models: Record<string, string>;
  created_at: string | null;
}

export interface BacktestRow {
  ipo_id: string;
  company: string;
  listing_date: string | null;
  issue_price: number | null;
  symbol: string | null;
  verdict: string | null;
  confidence: string | null;
  debate_id: string | null;
  listing_close: number | null;
  last_close: number | null;
  last_date: string | null;
  listing_gain_pct: number | null;
  current_return_pct: number | null;
  hit: boolean | null;
  price_source: string | null;
}

export interface ChunkRow {
  chunk_id: string;
  doc_id: string;
  doc_type: string | null;
  section: string;
  page: number;
  page_end: number;
  ordinal: number;
  chars: number;
  text: string;
}

export interface ChunkPage {
  total: number;
  offset: number;
  limit: number;
  sections: { section: string; count: number }[];
  items: ChunkRow[];
}

export interface EmbeddingStatus {
  doc_id: string;
  doc_type: string;
  filed_date: string | null;
  sqlite_chunks: number;
  vectors: number;
  in_sync: boolean;
  embedding_model: string;
  collection: string;
}

export interface FinancialRowData {
  statement: string;
  line_item: string;
  period: string;
  value_inr_mn: number;
  page: number;
  raw_label: string;
  basis: string;
  is_override: number;
}
