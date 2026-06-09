export type Dict = Record<string, unknown>;

export type DatasetResponse = {
  run_id: string;
  source: string;
  schema: Dict;
  raw_summary: Dict;
  preview: Dict[];
};

export type RawSummaryResponse = {
  run_id: string;
  schema: Dict;
  raw_summary: Dict;
  monthly_stats: Dict[];
  top_products: Dict[];
  top_products_by_quantity: Dict[];
  product_table: Dict[];
  preview: Dict[];
};

export type CompletedResultsResponse = {
  run_id: string;
  source: string;
  uploaded_files: string[];
  recognized_files: string[];
  missing_recommended: string[];
  validation_warnings: string[];
  outputs: string[];
};

export type PreprocessResponse = {
  run_id: string;
  preprocess_report: Dict;
  temporal_metadata: Dict;
  tx_before_filter_preview: Dict[];
  tx_after_filter_preview: Dict[];
  max_len_impact: Dict[];
  outputs: string[];
};

export type Phase1Response = {
  run_id: string;
  mining_summary: Dict;
  selected_shuis: Dict[];
  item_scores_flat: Dict[];
  outputs: string[];
};

export type Phase2Response = {
  run_id: string;
  summary: Dict;
  local_reports: Dict[];
  modifications_preview: Dict[];
  modified_transactions_preview: Dict[];
  outputs: string[];
};

export type Phase3Response = {
  run_id: string;
  report: Dict;
  window_metrics: Dict[];
  pattern_metrics: Dict[];
  modified_transactions_preview: Dict[];
  outputs: string[];
};

export type OutputFile = {
  file_name: string;
  size_bytes: number;
  download_url: string;
};

export type ExplorerResponse = {
  run_id: string;
  modified_transactions: Dict[];
  selected_patterns: Dict[];
  window_metrics: Dict[];
  pattern_metrics: Dict[];
  phase0_summary: Dict;
  phase2_summary: Dict;
  comparison_summary: Dict;
  comparison_tables: Record<string, Dict[]>;
};

export type TransactionDetailResponse = {
  run_id: string;
  window: string;
  tid: string;
  original: Dict | null;
  sanitized: Dict | null;
  item_rows: Dict[];
};
