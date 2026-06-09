import type {
  CompletedResultsResponse,
  DatasetResponse,
  ExplorerResponse,
  OutputFile,
  Phase1Response,
  Phase2Response,
  Phase3Response,
  PreprocessResponse,
  RawSummaryResponse,
  TransactionDetailResponse
} from "./types";

const API_BASE = import.meta.env.VITE_API_BASE ?? "http://127.0.0.1:8000";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const headers =
    init?.body instanceof FormData
      ? init.headers
      : init?.body
        ? { "Content-Type": "application/json", ...init?.headers }
        : init?.headers;
  const response = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers
  });
  if (!response.ok) {
    const errorBody = await response.json().catch(() => ({}));
    const detail = typeof errorBody.detail === "string" ? errorBody.detail : response.statusText;
    throw new Error(detail);
  }
  return response.json() as Promise<T>;
}

export const api = {
  baseUrl: API_BASE,
  health: () => request<{ status: string; service: string }>("/health"),
  pamiStatus: () => request<{ available: boolean; install_hint?: string; error?: string }>("/phase1/pami-status"),
  createDemo: (numRows = 1500, months = 6, seed = 42) =>
    request<DatasetResponse>(`/datasets/demo?num_rows=${numRows}&months=${months}&seed=${seed}`, {
      method: "POST"
    }),
  uploadCsv: (file: File) => {
    const formData = new FormData();
    formData.append("file", file);
    return request<DatasetResponse>("/datasets/upload", {
      method: "POST",
      body: formData
    });
  },
  uploadCompletedResults: (files: File[]) => {
    const formData = new FormData();
    files.forEach((file) => formData.append("files", file));
    return request<CompletedResultsResponse>("/results/upload", {
      method: "POST",
      body: formData
    });
  },
  rawSummary: (runId: string) => request<RawSummaryResponse>(`/datasets/${runId}/raw-summary`),
  preprocess: (runId: string, maxTransactionLen: number | null) =>
    request<PreprocessResponse>(`/preprocessing/${runId}`, {
      method: "POST",
      body: JSON.stringify({
        max_transaction_len: maxTransactionLen,
        window_granularity: "M",
        utility_mode: "round"
      })
    }),
  phase1: (
    runId: string,
    params = {
      mining_ratio: 0.01,
      sensitive_ratio: 0.015,
      candidate_mining_ratio: 0.015,
      min_peakness_ratio: 1.5,
      min_support_windows: 2,
      max_selected_per_window: 30,
      max_patterns_per_window: 3000,
      enable_twu_pruning: true
    }
  ) =>
    request<Phase1Response>(`/phase1/${runId}/mine`, {
      method: "POST",
      body: JSON.stringify(params)
    }),
  selectSensitiveCombos: (runId: string, patternKeys: string[]) =>
    request<{ run_id: string; selected_count: number }>(`/select-sensitive-combos?run_id=${encodeURIComponent(runId)}`, {
      method: "POST",
      body: JSON.stringify(patternKeys)
    }),
  phase2: (runId: string, ratio = 0.015, selectedPatternKeys: string[] = []) =>
    request<Phase2Response>(`/phase2/${runId}/sanitize`, {
      method: "POST",
      body: JSON.stringify({
        local_ratio: ratio,
        global_ratio: ratio,
        global_beta: 0.25,
        global_gamma: 0.75,
        selected_pattern_keys: selectedPatternKeys
      })
    }),
  phase3: (runId: string, ratio = 0.015) =>
    request<Phase3Response>(`/phase3/${runId}/verify`, {
      method: "POST",
      body: JSON.stringify({
        local_ratio: ratio,
        global_ratio: ratio
      })
  }),
  outputs: (runId: string) => request<{ run_id: string; outputs: OutputFile[] }>(`/runs/${runId}/outputs`),
  explorer: (runId: string) => request<ExplorerResponse>(`/runs/${runId}/explorer`),
  transactionDetail: (runId: string, window: string, tid: string) =>
    request<TransactionDetailResponse>(`/runs/${runId}/transactions/${encodeURIComponent(window)}/${encodeURIComponent(tid)}`),
  exportUrl: (runId: string, fileName: string) => `${API_BASE}/exports/${runId}/${fileName}`
};
