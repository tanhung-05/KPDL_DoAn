import {
  Activity,
  AlertCircle,
  AlertTriangle,
  BarChart3,
  ChevronsLeft,
  ChevronsRight,
  CheckCircle2,
  ChevronRight,
  Clock,
  Download,
  FileArchive,
  FileText,
  FileUp,
  Lock,
  Loader2,
  PackageCheck,
  RotateCcw,
  RefreshCw,
  Search,
  Settings2,
  ShieldCheck,
  ShoppingBasket,
  Sparkles,
  Trash2,
  Upload,
  X
} from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";
import { api } from "./api";
import type {
  CompletedResultsResponse,
  DatasetResponse,
  Dict,
  ExplorerResponse,
  OutputFile,
  Phase1Response,
  Phase2Response,
  Phase3Response,
  PreprocessResponse,
  RawSummaryResponse
} from "./types";

type SectionKey = "overview" | "combos" | "crossSell" | "sensitive" | "protect" | "reports" | "advanced";
type PresetKey = "fast" | "balanced" | "detailed";
type ActionKey = "upload" | "demo" | "completed" | "preprocess" | "mining" | "protect" | "verify" | "refresh";
type StepState = "locked" | "pending" | "ready" | "running" | "done" | "error";
type Toast = { id: number; type: "success" | "warning" | "error" | "info"; message: string };

type Preset = {
  label: string;
  help: string;
  max_transaction_len: number;
  mining_ratio: number;
  sensitive_ratio: number;
  candidate_mining_ratio: number;
  min_peakness_ratio: number;
  min_support_windows: number;
  max_selected_per_window: number;
  max_patterns_per_window: number;
};

type UploadedFileState = {
  name: string;
  size?: number;
  source: "csv" | "demo" | "completed";
};

const presets: Record<PresetKey, Preset> = {
  fast: {
    label: "Nhanh",
    help: "Ưu tiên demo nhanh, giới hạn combo dài và số combo nhạy cảm.",
    max_transaction_len: 20,
    mining_ratio: 0.01,
    sensitive_ratio: 0.02,
    candidate_mining_ratio: 0.02,
    min_peakness_ratio: 1.5,
    min_support_windows: 2,
    max_selected_per_window: 10,
    max_patterns_per_window: 1500
  },
  balanced: {
    label: "Cân bằng",
    help: "Mặc định cho demo đồ án: đủ chi tiết nhưng vẫn kiểm soát thời gian chạy.",
    max_transaction_len: 30,
    mining_ratio: 0.01,
    sensitive_ratio: 0.015,
    candidate_mining_ratio: 0.015,
    min_peakness_ratio: 1.5,
    min_support_windows: 2,
    max_selected_per_window: 30,
    max_patterns_per_window: 3000
  },
  detailed: {
    label: "Chi tiết",
    help: "Phân tích sâu hơn, có thể chậm với dữ liệu lớn.",
    max_transaction_len: 50,
    mining_ratio: 0.01,
    sensitive_ratio: 0.01,
    candidate_mining_ratio: 0.01,
    min_peakness_ratio: 1.3,
    min_support_windows: 2,
    max_selected_per_window: 50,
    max_patterns_per_window: 6000
  }
};

const sections: { key: SectionKey; label: string; icon: LucideIcon }[] = [
  { key: "overview", label: "Tổng quan", icon: BarChart3 },
  { key: "combos", label: "Combo giá trị cao", icon: Search },
  { key: "crossSell", label: "Gợi ý bán kèm", icon: ShoppingBasket },
  { key: "sensitive", label: "Combo nhạy cảm", icon: AlertTriangle },
  { key: "protect", label: "Bảo vệ dữ liệu", icon: ShieldCheck },
  { key: "reports", label: "Báo cáo", icon: Download },
  { key: "advanced", label: "Nâng cao", icon: Settings2 }
];

const requiredColumns = [
  ["Mã hóa đơn", "InvoiceNo"],
  ["Mã sản phẩm", "StockCode"],
  ["Số lượng", "Quantity"],
  ["Đơn giá", "UnitPrice"],
  ["Ngày bán", "InvoiceDate"]
];

const completedResultFiles = [
  "temporal_db_filtered.json",
  "phase1_peak_shui.json",
  "phase2_summary.json",
  "phase2_sanitized_db.json"
];

function readNumber(data: Dict | undefined, keys: string[], fallback = 0) {
  for (const key of keys) {
    const value = data?.[key];
    if (value !== undefined && value !== null && value !== "") {
      const numeric = Number(value);
      if (Number.isFinite(numeric)) return numeric;
    }
  }
  return fallback;
}

function readText(data: Dict | undefined, keys: string[], fallback = "-") {
  for (const key of keys) {
    const value = data?.[key];
    if (value !== undefined && value !== null && value !== "") return String(value);
  }
  return fallback;
}

function formatNumber(value: unknown, digits = 0) {
  const numeric = Number(value ?? 0);
  if (!Number.isFinite(numeric)) return "0";
  return numeric.toLocaleString("vi-VN", { maximumFractionDigits: digits });
}

function formatBytes(value?: number) {
  if (!value) return "Không rõ dung lượng";
  if (value < 1024) return `${value} B`;
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KB`;
  return `${(value / 1024 / 1024).toFixed(1)} MB`;
}

function formatPercent(value: unknown) {
  const numeric = Number(value ?? 0);
  const percent = Math.abs(numeric) <= 1 ? numeric * 100 : numeric;
  return `${percent.toLocaleString("vi-VN", { maximumFractionDigits: 2 })}%`;
}

function asArray(value: unknown): unknown[] {
  return Array.isArray(value) ? value : [];
}

function patternKey(row: Dict) {
  const key = readText(row, ["pattern_key"], "");
  if (key) return key;
  const items = asArray(row.items).map(String);
  return items.join(" ");
}

function comboLabel(row: Dict) {
  const labels = asArray(row.product_labels).map(String).filter(Boolean);
  if (labels.length) return labels.join(" + ");
  const items = asArray(row.items).map(String).filter(Boolean);
  if (items.length) return items.join(" + ");
  return readText(row, ["pattern_key", "combo"], "Combo chưa rõ");
}

function peakWindow(row: Dict) {
  const peaks = asArray(row.peak_windows).map(String).filter(Boolean);
  return peaks[0] ?? readText(row, ["selected_window", "window", "peak_window"], "-");
}

function businessReason(row: Dict) {
  const peakness = readNumber(row, ["peakness_ratio"], 0);
  if (peakness >= 2) return `Tăng mạnh trong tháng ${peakWindow(row)}. Nên theo dõi trong chiến dịch khuyến mãi.`;
  if (readNumber(row, ["window_utility", "utility", "total_utility"], 0) > 0) {
    return "Có thể dùng làm combo bán kèm vì cùng tạo doanh thu đóng góp cao.";
  }
  return "Combo có giá trị cao nhưng cần cân nhắc bảo vệ khi chia sẻ dữ liệu.";
}

function mapComboRow(row: Dict): Dict {
  return {
    key: patternKey(row),
    "Combo sản phẩm": comboLabel(row),
    "Doanh thu đóng góp": formatNumber(readNumber(row, ["window_utility", "utility", "total_utility"], 0)),
    "Tháng nổi bật": peakWindow(row),
    "Mức độ nổi bật": formatNumber(readNumber(row, ["peakness_ratio"], 0), 2),
    "Số tháng xuất hiện": formatNumber(readNumber(row, ["support_windows"], 0)),
    "Gợi ý kinh doanh": businessReason(row)
  };
}

function crossSellRows(comboRows: Dict[]) {
  return comboRows.flatMap((row) => {
    const combo = comboLabel(row).split(" + ").filter(Boolean);
    if (combo.length < 2) return [];
    return combo.map((main) => ({
      "Sản phẩm chính": main,
      "Nên gợi ý bán kèm": combo.filter((item) => item !== main).join(", "),
      "Combo gốc": combo.join(" + "),
      "Doanh thu combo": formatNumber(readNumber(row, ["window_utility", "utility", "total_utility"], 0)),
      "Tháng nổi bật": peakWindow(row),
      "Lý do gợi ý": `Cùng xuất hiện trong combo có doanh thu cao${peakWindow(row) !== "-" ? `, nổi bật tháng ${peakWindow(row)}` : ""}.`
    }));
  });
}

export function App() {
  const [active, setActive] = useState<SectionKey>("overview");
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [runId, setRunId] = useState(localStorage.getItem("ta_pphuim_run_id") ?? "");
  const [uploadedFile, setUploadedFile] = useState<UploadedFileState | null>(null);
  const [dataset, setDataset] = useState<DatasetResponse | null>(null);
  const [completedResults, setCompletedResults] = useState<CompletedResultsResponse | null>(null);
  const [rawSummary, setRawSummary] = useState<RawSummaryResponse | null>(null);
  const [preprocess, setPreprocess] = useState<PreprocessResponse | null>(null);
  const [phase1, setPhase1] = useState<Phase1Response | null>(null);
  const [phase2, setPhase2] = useState<Phase2Response | null>(null);
  const [phase3, setPhase3] = useState<Phase3Response | null>(null);
  const [explorer, setExplorer] = useState<ExplorerResponse | null>(null);
  const [outputs, setOutputs] = useState<OutputFile[]>([]);
  const [pami, setPami] = useState<{ available: boolean; install_hint?: string; error?: string } | null>(null);
  const [presetKey, setPresetKey] = useState<PresetKey>("balanced");
  const [showAdvanced, setShowAdvanced] = useState(false);
  const [selectedKeys, setSelectedKeys] = useState<string[]>([]);
  const [busyKey, setBusyKey] = useState<ActionKey | "">("");
  const [busyLabel, setBusyLabel] = useState("");
  const [lastError, setLastError] = useState("");
  const [toasts, setToasts] = useState<Toast[]>([]);

  const preset = presets[presetKey];
  const isBusy = Boolean(busyKey);

  useEffect(() => {
    api.pamiStatus().then(setPami).catch(() => setPami(null));
  }, []);

  useEffect(() => {
    if (!runId) return;
    localStorage.setItem("ta_pphuim_run_id", runId);
    api.outputs(runId).then((res) => setOutputs(res.outputs)).catch(() => undefined);
    api.rawSummary(runId).then(setRawSummary).catch(() => undefined);
    api.explorer(runId).then(setExplorer).catch(() => undefined);
  }, [runId]);

  useEffect(() => {
    if (!toasts.length) return;
    const timer = window.setTimeout(() => {
      setToasts((items) => items.slice(1));
    }, 4200);
    return () => window.clearTimeout(timer);
  }, [toasts]);

  const comboSource = useMemo(() => {
    if (explorer?.selected_patterns.length) return explorer.selected_patterns;
    return phase1?.selected_shuis ?? [];
  }, [explorer, phase1]);

  const combos = useMemo(() => comboSource.map(mapComboRow), [comboSource]);
  const suggestions = useMemo(() => crossSellRows(comboSource).slice(0, 80), [comboSource]);

  useEffect(() => {
    if (!comboSource.length || selectedKeys.length) return;
    setSelectedKeys(comboSource.map(patternKey).filter(Boolean).slice(0, preset.max_selected_per_window));
  }, [comboSource, preset.max_selected_per_window, selectedKeys.length]);

  const ready = {
    data: Boolean(runId && rawSummary),
    preprocess: Boolean(preprocess || outputs.some((item) => item.file_name === "temporal_db.json")),
    combos: Boolean(combos.length || outputs.some((item) => item.file_name === "phase1_peak_shui.json")),
    protected: Boolean(phase2 || outputs.some((item) => item.file_name === "phase2_sanitized_db.json")),
    verified: Boolean(phase3 || outputs.some((item) => item.file_name === "phase3_verification_report.json"))
  };

  const summary = rawSummary?.raw_summary ?? dataset?.raw_summary;
  const localLeaks = readNumber(phase3?.report, ["local_violations", "local_violations_after_patch"], readNumber(phase2?.summary, ["local_violations_after_patch", "local_violations_after"], 0));
  const globalLeaks = readNumber(phase3?.report, ["global_leaks", "post_patch_global_leaks"], readNumber(phase2?.summary, ["post_patch_global_leaks", "post_patch_leaks"], 0));
  const isSafe = Boolean(phase3?.report?.PHASE3_PASS) || Boolean(phase2 && localLeaks === 0 && globalLeaks === 0);

  const stepStates = {
    upload: busyKey === "upload" || busyKey === "demo" || busyKey === "completed" ? "running" : ready.data || completedResults ? "done" : "ready",
    preprocess: busyKey === "preprocess" ? "running" : ready.preprocess ? "done" : ready.data ? "ready" : "locked",
    mining: busyKey === "mining" ? "running" : ready.combos ? "done" : ready.preprocess ? "ready" : "locked",
    sensitive: selectedKeys.length ? "done" : ready.combos ? "ready" : "locked",
    protect: busyKey === "protect" ? "running" : ready.protected ? "done" : ready.combos && selectedKeys.length ? "ready" : "locked",
    verify: busyKey === "verify" ? "running" : ready.verified ? "done" : ready.protected ? "ready" : "locked",
    reports: outputs.length ? "done" : ready.verified || ready.protected ? "ready" : "locked"
  } satisfies Record<string, StepState>;

  const navStates: Record<SectionKey, StepState> = {
    overview: ready.data ? "done" : busyKey === "upload" || busyKey === "demo" ? "running" : "ready",
    combos: ready.combos ? "done" : busyKey === "mining" ? "running" : ready.preprocess ? "ready" : "locked",
    crossSell: suggestions.length ? "done" : ready.combos ? "ready" : "locked",
    sensitive: selectedKeys.length ? "done" : ready.combos ? "ready" : "locked",
    protect: ready.protected ? "done" : busyKey === "protect" ? "running" : ready.combos && selectedKeys.length ? "ready" : "locked",
    reports: outputs.length ? "done" : "locked",
    advanced: "ready"
  };

  function pushToast(type: Toast["type"], message: string) {
    setToasts((items) => [...items, { id: Date.now() + Math.random(), type, message }]);
  }

  async function runAction<T>(
    key: ActionKey,
    label: string,
    action: () => Promise<T>,
    after?: (result: T) => void,
    successMessage?: string
  ) {
    if (busyKey) return;
    setBusyKey(key);
    setBusyLabel(label);
    setLastError("");
    try {
      const result = await action();
      after?.(result);
      const activeRunId = runId || (result as { run_id?: string }).run_id;
      if (activeRunId) {
        const refreshed = await api.outputs(activeRunId);
        setOutputs(refreshed.outputs);
        await api.explorer(activeRunId).then(setExplorer).catch(() => undefined);
      }
      if (successMessage) pushToast("success", successMessage);
    } catch (err) {
      console.error(err);
      const message = err instanceof Error ? err.message : "Có lỗi xảy ra. Vui lòng kiểm tra dữ liệu và thử lại.";
      setLastError(message);
      pushToast("error", message);
    } finally {
      setBusyKey("");
      setBusyLabel("");
    }
  }

  function acceptDataset(result: DatasetResponse, file?: UploadedFileState) {
    setDataset(result);
    setCompletedResults(null);
    setUploadedFile(file ?? { name: result.source === "synthetic_demo" ? "Dữ liệu mẫu" : "CSV đã upload", source: result.source === "synthetic_demo" ? "demo" : "csv" });
    setRawSummary({
      run_id: result.run_id,
      schema: result.schema,
      raw_summary: result.raw_summary,
      monthly_stats: [],
      top_products: [],
      top_products_by_quantity: [],
      product_table: [],
      preview: result.preview
    });
    setRunId(result.run_id);
    setPreprocess(null);
    setPhase1(null);
    setPhase2(null);
    setPhase3(null);
    setExplorer(null);
    setSelectedKeys([]);
    setActive("overview");
  }

  function acceptCompletedResults(result: CompletedResultsResponse, files: File[]) {
    setCompletedResults(result);
    setDataset(null);
    setUploadedFile({ name: files.length === 1 ? files[0].name : `${files.length} file kết quả`, size: files.reduce((total, file) => total + file.size, 0), source: "completed" });
    setRawSummary(null);
    setRunId(result.run_id);
    setOutputs(result.outputs.map((fileName) => ({ file_name: fileName, size_bytes: 0, download_url: "" })));
    setPreprocess(null);
    setPhase1(null);
    setPhase2(null);
    setPhase3(null);
    setSelectedKeys([]);
    setActive("reports");
  }

  function resetDataset() {
    setRunId("");
    localStorage.removeItem("ta_pphuim_run_id");
    setUploadedFile(null);
    setDataset(null);
    setCompletedResults(null);
    setRawSummary(null);
    setPreprocess(null);
    setPhase1(null);
    setPhase2(null);
    setPhase3(null);
    setExplorer(null);
    setOutputs([]);
    setSelectedKeys([]);
    setLastError("");
    pushToast("info", "Đã xóa dataset khỏi phiên làm việc hiện tại.");
  }

  async function refreshSession() {
    if (!runId) {
      pushToast("warning", "Chưa có phiên dữ liệu để làm mới.");
      return;
    }
    await runAction(
      "refresh",
      "Đang làm mới trạng thái phiên...",
      async () => {
        const refreshed = await api.outputs(runId);
        setOutputs(refreshed.outputs);
        await api.rawSummary(runId).then(setRawSummary).catch(() => undefined);
        await api.explorer(runId).then(setExplorer).catch(() => undefined);
        return { run_id: runId };
      },
      undefined,
      "Đã làm mới trạng thái phiên."
    );
  }

  function uploadCsv(file: File) {
    runAction(
      "upload",
      "Đang tải dữ liệu lên...",
      () => api.uploadCsv(file),
      (result) => acceptDataset(result, { name: file.name, size: file.size, source: "csv" }),
      "Upload thành công. Dữ liệu đã sẵn sàng để phân tích."
    );
  }

  function uploadCompleted(files: File[]) {
    runAction(
      "completed",
      "Đang tải kết quả đã phân tích...",
      () => api.uploadCompletedResults(files),
      (result) => acceptCompletedResults(result, files),
      "Đã tải bộ kết quả đã phân tích."
    );
  }

  async function runPreprocess() {
    if (!runId) {
      pushToast("warning", "Chưa thể chạy vì thiếu dữ liệu bán hàng.");
      return;
    }
    await runAction(
      "preprocess",
      "Đang chuẩn hóa dữ liệu bán hàng...",
      () => api.preprocess(runId, preset.max_transaction_len),
      setPreprocess,
      "Chuẩn hóa dữ liệu hoàn tất."
    );
  }

  async function runMining() {
    if (!runId) {
      pushToast("warning", "Hãy upload CSV hoặc dùng dữ liệu mẫu trước.");
      return;
    }
    if (!pami?.available) {
      pushToast("warning", "EFIM/PAMI chưa cài. Bạn vẫn có thể tải kết quả đã phân tích.");
      return;
    }
    const confirmed = window.confirm(
      "Bước này có thể mất thời gian với dữ liệu lớn vì cần khai phá nhiều tổ hợp sản phẩm. Bạn muốn tiếp tục?"
    );
    if (!confirmed) return;
    await runAction(
      "mining",
      "Đang tìm combo sản phẩm giá trị cao...",
      async () => {
        if (!ready.preprocess) {
          const prep = await api.preprocess(runId, preset.max_transaction_len);
          setPreprocess(prep);
        }
        return api.phase1(runId, {
          mining_ratio: preset.mining_ratio,
          sensitive_ratio: preset.sensitive_ratio,
          candidate_mining_ratio: preset.candidate_mining_ratio,
          min_peakness_ratio: preset.min_peakness_ratio,
          min_support_windows: preset.min_support_windows,
          max_selected_per_window: preset.max_selected_per_window,
          max_patterns_per_window: preset.max_patterns_per_window,
          enable_twu_pruning: true
        });
      },
      setPhase1,
      "Tìm combo giá trị cao hoàn tất."
    );
    setActive("combos");
  }

  async function runProtection() {
    if (!selectedKeys.length) {
      pushToast("warning", "Chưa chọn combo cần bảo vệ.");
      return;
    }
    await runAction(
      "protect",
      "Đang ẩn combo khỏi dữ liệu chia sẻ...",
      async () => {
        await api.selectSensitiveCombos(runId, selectedKeys);
        return api.phase2(runId, preset.sensitive_ratio, selectedKeys);
      },
      setPhase2,
      "Bảo vệ dữ liệu hoàn tất."
    );
  }

  async function runVerification() {
    await runAction(
      "verify",
      "Đang kiểm tra rò rỉ sau xử lý...",
      () => api.phase3(runId, preset.sensitive_ratio),
      setPhase3,
      "Kiểm tra rò rỉ hoàn tất."
    );
  }

  return (
    <main className={sidebarCollapsed ? "app-shell sidebar-collapsed" : "app-shell"}>
      <aside className="sidebar">
        <div className="brand">
          <div className="brand-mark">
            <Activity size={22} />
          </div>
          <div className="brand-copy">
            <strong>Retail Insight & Privacy</strong>
            <span>Phân tích bán hàng & bảo vệ dữ liệu kinh doanh</span>
          </div>
          <button
            className="sidebar-toggle"
            onClick={() => setSidebarCollapsed(!sidebarCollapsed)}
            title={sidebarCollapsed ? "Mở rộng menu" : "Thu gọn menu"}
          >
            {sidebarCollapsed ? <ChevronsRight size={18} /> : <ChevronsLeft size={18} />}
          </button>
        </div>
        <nav className="nav-tabs">
          {sections.map((section) => {
            const Icon = section.icon;
            const state = navStates[section.key];
            return (
              <button
                className={`nav-tab ${active === section.key ? "active" : ""} ${state === "locked" ? "disabled" : ""}`}
                key={section.key}
                onClick={() => setActive(section.key)}
                title={state === "locked" ? `${section.label} - cần hoàn tất bước trước` : section.label}
              >
                <Icon size={18} />
                <span>{section.label}</span>
              </button>
            );
          })}
        </nav>
        {runId ? (
          <details className="run-box">
            <summary>Chi tiết phiên</summary>
            <code>{runId}</code>
          </details>
        ) : null}
      </aside>

      <section className="workspace">
        <header className="app-header">
          <div>
            <h1>Retail Insight & Privacy</h1>
            <p>Phân tích bán hàng & bảo vệ dữ liệu kinh doanh</p>
          </div>
          <div className="header-actions">
            <DatasetPill
              uploadedFile={uploadedFile}
              rows={readNumber(summary, ["total_rows"], 0)}
              isBusy={isBusy}
              isReady={ready.data || Boolean(completedResults)}
              hasError={Boolean(lastError)}
            />
            <div className="session-actions">
              <button className="icon-button" disabled={!runId || isBusy} onClick={refreshSession} title="Làm mới trạng thái phiên">
                {busyKey === "refresh" ? <Loader2 size={17} className="spinner" /> : <RefreshCw size={17} />}
              </button>
              <button className="icon-button danger" disabled={!runId || isBusy} onClick={resetDataset} title="Dọn phiên / đổi dữ liệu">
                <RotateCcw size={17} />
              </button>
            </div>
          </div>
        </header>

        <ToastStack toasts={toasts} onClose={(id) => setToasts((items) => items.filter((item) => item.id !== id))} />

        {lastError ? (
          <div className="alert error">
            <AlertCircle size={18} />
            <div>
              <strong>Lỗi backend/API</strong>
              <p>{lastError}</p>
            </div>
            <button className="ghost-button" onClick={() => setLastError("")}>
              Đóng
            </button>
          </div>
        ) : null}

        {busyKey ? (
          <div className="loading-overlay">
            <Loader2 size={20} className="spinner" />
            <span>{busyLabel}</span>
          </div>
        ) : null}

        <ProgressStepper states={stepStates} />

        {active === "overview" ? (
          <OverviewSection
            dataset={dataset}
            rawSummary={rawSummary}
            completedResults={completedResults}
            uploadedFile={uploadedFile}
            isBusy={isBusy}
            busyKey={busyKey}
            onUpload={uploadCsv}
            onCompletedUpload={uploadCompleted}
            onDemo={() =>
              runAction(
                "demo",
                "Đang tạo dữ liệu mẫu...",
                () => api.createDemo(),
                (result) => acceptDataset(result, { name: "Dữ liệu mẫu 1.500 dòng", source: "demo" }),
                "Đã dùng dữ liệu mẫu."
              )
            }
            onReset={resetDataset}
            onPreprocess={runPreprocess}
            canPreprocess={Boolean(runId)}
          />
        ) : null}

        {active === "combos" ? (
          <CombosSection
            disabled={!runId || !pami?.available || isBusy}
            locked={!ready.preprocess}
            pami={pami}
            combos={combos}
            miningSummary={phase1?.mining_summary}
            onRun={runMining}
            isLoading={busyKey === "mining"}
          />
        ) : null}

        {active === "crossSell" ? <CrossSellSection rows={suggestions} locked={!ready.combos} /> : null}

        {active === "sensitive" ? (
          <SensitiveSection
            comboSource={comboSource}
            selectedKeys={selectedKeys}
            setSelectedKeys={setSelectedKeys}
          />
        ) : null}

        {active === "protect" ? (
          <ProtectSection
            selectedCount={selectedKeys.length}
            phase2={phase2}
            phase3={phase3}
            canProtect={ready.combos && selectedKeys.length > 0 && !isBusy}
            canVerify={ready.protected && !isBusy}
            isProtecting={busyKey === "protect"}
            isVerifying={busyKey === "verify"}
            onProtect={runProtection}
            onVerify={runVerification}
          />
        ) : null}

        {active === "reports" ? <ReportsSection runId={runId} outputs={outputs} explorer={explorer} locked={!outputs.length} /> : null}

        {active === "advanced" ? (
          <AdvancedSection
            presetKey={presetKey}
            setPresetKey={setPresetKey}
            showAdvanced={showAdvanced}
            setShowAdvanced={setShowAdvanced}
          />
        ) : null}
      </section>
    </main>
  );
}

function DatasetPill({
  uploadedFile,
  rows,
  isBusy,
  isReady,
  hasError
}: {
  uploadedFile: UploadedFileState | null;
  rows: number;
  isBusy: boolean;
  isReady: boolean;
  hasError: boolean;
}) {
  const label = uploadedFile?.name ?? "Chưa có file";
  const status = hasError ? "Lỗi" : isBusy ? "Đang xử lý" : isReady ? "Sẵn sàng" : "Chưa có dữ liệu";
  return (
    <div className={hasError ? "dataset-pill error" : isReady ? "dataset-pill ready" : "dataset-pill"}>
      <span className="status-dot" />
      <div>
        <strong>Dataset: {label}</strong>
        <small>{rows ? `${formatNumber(rows)} dòng • ${status}` : status}</small>
      </div>
    </div>
  );
}

function ToastStack({ toasts, onClose }: { toasts: Toast[]; onClose: (id: number) => void }) {
  return (
    <div className="toast-stack">
      {toasts.map((toast) => (
        <div className={`toast ${toast.type}`} key={toast.id}>
          <span>{toast.message}</span>
          <button onClick={() => onClose(toast.id)} aria-label="Đóng thông báo">
            <X size={15} />
          </button>
        </div>
      ))}
    </div>
  );
}

function StatusBadge({ state, compact = false }: { state: StepState; compact?: boolean }) {
  const labels: Record<StepState, string> = {
    locked: "Chưa sẵn sàng",
    pending: "Chưa bắt đầu",
    ready: "Sẵn sàng",
    running: "Đang xử lý",
    done: "Hoàn tất",
    error: "Có lỗi"
  };
  return (
    <span className={`status-badge ${state}`}>
      {state === "running" ? <Loader2 size={compact ? 12 : 14} className="spinner" /> : null}
      {state === "locked" ? <Lock size={compact ? 12 : 14} /> : null}
      {state === "done" ? <CheckCircle2 size={compact ? 12 : 14} /> : null}
      {!compact || state !== "pending" ? labels[state] : ""}
    </span>
  );
}

function ProgressStepper({ states }: { states: Record<string, StepState> }) {
  const steps: { key: keyof typeof states; title: string; icon: LucideIcon }[] = [
    { key: "upload", title: "Dữ liệu", icon: Upload },
    { key: "preprocess", title: "Chuẩn hóa", icon: PackageCheck },
    { key: "mining", title: "Combo", icon: Search },
    { key: "sensitive", title: "Nhạy cảm", icon: AlertTriangle },
    { key: "protect", title: "Bảo vệ", icon: ShieldCheck },
    { key: "verify", title: "Kiểm tra", icon: CheckCircle2 },
    { key: "reports", title: "Báo cáo", icon: Download }
  ];
  const currentIndex = Math.max(
    0,
    steps.findIndex((step) => states[step.key] === "running" || states[step.key] === "ready")
  );
  const doneCount = steps.filter((step) => states[step.key] === "done").length;
  const progress = Math.round((doneCount / steps.length) * 100);
  return (
    <section className="workflow-strip" aria-label="Tiến trình xử lý">
      <div className="workflow-copy">
        <span>Tiến trình</span>
        <strong>{progress}% hoàn tất</strong>
      </div>
      <div className="workflow-line">
        <span style={{ width: `${progress}%` }} />
      </div>
      <div className="workflow-steps">
        {steps.map((step, index) => {
          const Icon = step.icon;
          const state = states[step.key];
          return (
            <div className={`workflow-step ${state} ${index === currentIndex ? "current" : ""}`} key={String(step.key)} title={step.title}>
              <span>
                {state === "running" ? <Loader2 size={14} className="spinner" /> : <Icon size={14} />}
              </span>
              <small>{step.title}</small>
            </div>
          );
        })}
      </div>
    </section>
  );
}

function OverviewSection({
  dataset,
  rawSummary,
  completedResults,
  uploadedFile,
  isBusy,
  busyKey,
  onUpload,
  onCompletedUpload,
  onDemo,
  onReset,
  onPreprocess,
  canPreprocess
}: {
  dataset: DatasetResponse | null;
  rawSummary: RawSummaryResponse | null;
  completedResults: CompletedResultsResponse | null;
  uploadedFile: UploadedFileState | null;
  isBusy: boolean;
  busyKey: ActionKey | "";
  onUpload: (file: File) => void;
  onCompletedUpload: (files: File[]) => void;
  onDemo: () => void;
  onReset: () => void;
  onPreprocess: () => void;
  canPreprocess: boolean;
}) {
  const summary = rawSummary?.raw_summary ?? dataset?.raw_summary;
  const schema = rawSummary?.schema ?? dataset?.schema;
  const missing = asArray(schema?.missing_columns).map(String);
  const hasData = Boolean(rawSummary || dataset || completedResults);
  const [uploadMode, setUploadMode] = useState<"new" | "completed">("new");

  return (
    <div className="grid two">
      <section className="hero-panel full">
        <div>
          <span className="eyebrow">Retail analytics workspace</span>
          <h2>Biến dữ liệu bán hàng thành insight có thể chia sẻ an toàn.</h2>
          <p>
            Upload CSV, khai phá combo giá trị cao, chọn mẫu nhạy cảm và xuất báo cáo bảo vệ dữ liệu trong một luồng rõ ràng.
          </p>
        </div>
        <div className={hasData ? "dataset-card ready" : "dataset-card"}>
          <div className="dataset-card-icon">
            {hasData ? <CheckCircle2 size={22} /> : <FileUp size={22} />}
          </div>
          <div>
            <span>Dataset hiện tại</span>
            <strong>{uploadedFile?.name ?? "Chưa có dữ liệu bán hàng"}</strong>
            <small>
              {hasData
                ? `${formatNumber(readNumber(summary, ["total_rows"], 0)) || "0"} dòng • Sẵn sàng phân tích`
                : "Upload CSV hoặc dùng dữ liệu mẫu để bắt đầu"}
            </small>
          </div>
        </div>
      </section>

      <section className="action-card full">
        <div className="section-head">
          <div>
            <h2>Bắt đầu phân tích</h2>
            <p>Chọn một nguồn dữ liệu. Mỗi lần chỉ hiển thị một luồng để màn hình gọn hơn.</p>
          </div>
          <div className="segmented-control" role="tablist" aria-label="Chọn nguồn dữ liệu">
            <button className={uploadMode === "new" ? "active" : ""} onClick={() => setUploadMode("new")} type="button">
              Dữ liệu mới
            </button>
            <button className={uploadMode === "completed" ? "active" : ""} onClick={() => setUploadMode("completed")} type="button">
              Kết quả đã có
            </button>
          </div>
        </div>

        {uploadMode === "new" ? (
          <div className="upload-flow">
            <UploadZone
              title="Kéo thả CSV vào đây"
              description="Hoặc chọn file bán hàng từ máy tính"
              accept=".csv"
              disabled={isBusy}
              loading={busyKey === "upload"}
              onFiles={(files) => files[0] && onUpload(files[0])}
            />
            <div className="button-row">
              <LoadingButton kind="secondary" loading={busyKey === "demo"} disabled={isBusy} onClick={onDemo}>
                <Sparkles size={18} />
                Dùng dữ liệu mẫu
              </LoadingButton>
              <LoadingButton kind="ghost" disabled={!uploadedFile || isBusy} onClick={onReset}>
                <Trash2 size={18} />
                Xóa / đổi file
              </LoadingButton>
              <LoadingButton kind="primary" loading={busyKey === "preprocess"} disabled={!canPreprocess || isBusy} onClick={onPreprocess}>
                <PackageCheck size={18} />
                Chuẩn hóa dữ liệu
              </LoadingButton>
            </div>
            {uploadedFile ? (
              <div className="file-card">
                <FileText size={18} />
                <div>
                  <strong>{uploadedFile.name}</strong>
                  <span>{formatBytes(uploadedFile.size)} • {hasData ? "Dữ liệu đã sẵn sàng để phân tích" : "Đang chờ xử lý"}</span>
                </div>
              </div>
            ) : null}
            <details className="technical subtle">
              <summary>Cột CSV cần có</summary>
              <div className="column-map">
                {requiredColumns.map(([label, column]) => (
                  <span key={column}>
                    {label} <code>{column}</code>
                  </span>
                ))}
              </div>
            </details>
          </div>
        ) : (
          <div className="upload-flow">
            <UploadZone
              title="Kéo thả ZIP/JSON/XLSX vào đây"
              description="Dùng khi EFIM đã chạy trên Kaggle/Colab hoặc máy khác"
              accept=".json,.csv,.xlsx,.txt,.zip"
              multiple
              disabled={isBusy}
              loading={busyKey === "completed"}
              onFiles={onCompletedUpload}
            />
            <CompletedResultsStatus completedResults={completedResults} />
          </div>
        )}

        <div className={missing.length ? "notice warn" : hasData ? "notice ok" : "notice"}>
          {hasData
            ? missing.length
              ? `File thiếu cột: ${missing.join(", ")}`
              : `Trạng thái tốt: ${formatNumber(summary?.total_rows)} dòng, ${formatNumber(summary?.total_columns)} cột.`
            : "Chưa có dữ liệu. Hãy upload CSV, dùng dữ liệu mẫu hoặc tải bộ kết quả đã phân tích."}
        </div>
      </section>

      {!hasData ? (
        <section className="panel full">
          <EmptyState
            icon={BarChart3}
            title="Dashboard sẽ xuất hiện sau khi có dữ liệu"
            text="Các chỉ số, biểu đồ tháng, bảng sản phẩm và kết quả bảo vệ dữ liệu được ẩn để màn hình đầu tiên nhẹ hơn."
          />
        </section>
      ) : (
        <>
      <section className="panel full">
        <div className="section-head">
          <div>
            <h2>Tổng quan bán hàng</h2>
            <p>Những chỉ số kinh doanh chính sau khi dữ liệu sẵn sàng.</p>
          </div>
        </div>
        <div className="metric-grid">
          <Metric icon={BarChart3} label="Tổng doanh thu" value={formatNumber(readNumber(summary, ["total_revenue", "raw_total_utility"], 0))} hint="Tổng giá trị giao dịch hợp lệ" />
          <Metric icon={FileText} label="Số hóa đơn" value={formatNumber(readNumber(summary, ["valid_invoices", "total_invoices"], 0))} hint="Hóa đơn không bị hủy" />
          <Metric icon={ShoppingBasket} label="Số sản phẩm" value={formatNumber(readNumber(summary, ["total_items"], 0))} hint="Mã sản phẩm khác nhau" />
          <Metric icon={Clock} label="Số tháng dữ liệu" value={formatNumber(readNumber(summary, ["data_months"], 0))} hint="Temporal window" />
          <Metric icon={Activity} label="Giá trị hóa đơn TB" value={formatNumber(readNumber(summary, ["average_invoice_value"], 0))} hint="Doanh thu trung bình mỗi hóa đơn" />
          <Metric icon={CheckCircle2} label="Giao dịch hợp lệ" value={formatNumber(readNumber(summary, ["valid_transactions"], 0))} hint="Dòng dùng được sau kiểm tra" />
          <Metric icon={AlertCircle} label="Dòng bị loại" value={formatNumber(readNumber(summary, ["removed_rows"], 0))} hint="Hóa đơn hủy hoặc dữ liệu lỗi" />
          <Metric icon={ShieldCheck} label="Trạng thái an toàn" value={completedResults ? "Đã tải kết quả" : "Chưa kiểm tra"} hint="Sau Phase 3 sẽ có kết luận" />
        </div>
      </section>

      <section className="panel wide">
        <h2>Doanh thu theo tháng</h2>
        <MiniBars rows={rawSummary?.monthly_stats ?? []} xKey="WindowKey" yKey="total_utility" />
      </section>
      <section className="panel wide">
        <h2>Số hóa đơn theo tháng</h2>
        <MiniBars rows={rawSummary?.monthly_stats ?? []} xKey="WindowKey" yKey="invoices" />
      </section>
      <section className="panel wide">
        <h2>Top sản phẩm theo doanh thu</h2>
        <DataTable rows={(rawSummary?.top_products ?? []).slice(0, 20)} />
      </section>
      <section className="panel wide">
        <h2>Top sản phẩm theo số lượng bán</h2>
        <DataTable rows={(rawSummary?.top_products_by_quantity ?? []).slice(0, 20)} />
      </section>
      <section className="panel full">
        <h2>Bảng sản phẩm</h2>
        <DataTable rows={(rawSummary?.product_table ?? []).slice(0, 50)} />
      </section>
      <section className="panel full">
        <h2>Preview 10 dòng đầu</h2>
        <DataTable rows={(dataset?.preview ?? rawSummary?.preview ?? []).slice(0, 10)} />
      </section>
        </>
      )}
    </div>
  );
}

function CompletedResultsStatus({ completedResults }: { completedResults: CompletedResultsResponse | null }) {
  const recognized = new Set(completedResults?.recognized_files ?? []);
  return (
    <details className="completed-list">
      <summary>
        <span>Checklist file kết quả</span>
        <small>{completedResults ? `${recognized.size} file đã nhận diện` : "Mở để xem file khuyến nghị"}</small>
      </summary>
      <div className="completed-files">
        {completedResultFiles.map((file) => {
          const hasFile = recognized.has(file) || recognized.has(file.replace("_filtered", ""));
          return (
            <div className={hasFile ? "completed-file ok" : "completed-file missing"} key={file}>
              <span>{file}</span>
              {hasFile ? <CheckCircle2 size={16} /> : <Clock size={16} />}
            </div>
          );
        })}
      </div>
      {completedResults?.validation_warnings.length ? (
        <div className="notice warn">
          {completedResults.validation_warnings.slice(0, 4).map((warning) => (
            <p key={warning}>{warning}</p>
          ))}
        </div>
      ) : null}
    </details>
  );
}

function CombosSection({
  disabled,
  locked,
  pami,
  combos,
  miningSummary,
  onRun,
  isLoading
}: {
  disabled: boolean;
  locked: boolean;
  pami: { available: boolean; install_hint?: string; error?: string } | null;
  combos: Dict[];
  miningSummary?: Dict;
  onRun: () => void;
  isLoading: boolean;
}) {
  return (
    <section className="panel full">
      <div className="section-head">
        <div>
          <h2>Combo sản phẩm giá trị cao</h2>
          <p>Hệ thống tìm các nhóm sản phẩm tạo doanh thu cao khi xuất hiện cùng nhau trong hóa đơn.</p>
        </div>
        <LoadingButton kind="primary" loading={isLoading} disabled={disabled} onClick={onRun}>
          <Search size={18} />
          Tìm combo giá trị cao
        </LoadingButton>
      </div>
      {locked ? (
        <EmptyState icon={Lock} title="Chưa sẵn sàng chạy combo" text="Hãy upload dữ liệu và chạy chuẩn hóa dữ liệu trước." />
      ) : !pami?.available ? (
        <EmptyState icon={AlertTriangle} title="EFIM/PAMI chưa được cài" text={pami?.install_hint ?? "Bạn vẫn có thể tải kết quả đã phân tích để xem dashboard."} />
      ) : combos.length ? (
        <DataTable rows={combos.slice(0, 80)} />
      ) : (
        <EmptyState icon={Search} title="Chưa có combo sản phẩm" text="Hãy chạy phân tích combo giá trị cao hoặc tải kết quả đã phân tích." />
      )}
      <details className="technical">
        <summary>Chi tiết kỹ thuật</summary>
        <div className="metric-grid compact">
          <Metric icon={Search} label="Thuật toán backend" value="EFIM" hint="Chỉ hiển thị trong phần kỹ thuật" />
          <Metric icon={PackageCheck} label="Số HUI/PSHUI" value={formatNumber(readNumber(miningSummary, ["selected_patterns"], combos.length))} hint="Combo được chọn" />
          <Metric icon={AlertCircle} label="Số window lỗi" value={formatNumber(readNumber(miningSummary, ["failed_windows"], 0))} hint="Nếu có" />
          <Metric icon={Activity} label="Pattern thô" value={formatNumber(readNumber(miningSummary, ["total_raw_patterns"], 0))} hint="Trước khi lọc" />
        </div>
      </details>
    </section>
  );
}

function CrossSellSection({ rows, locked }: { rows: Dict[]; locked: boolean }) {
  return (
    <section className="panel full">
      <h2>Gợi ý bán kèm</h2>
      <p className="muted">Gợi ý được sinh trực tiếp từ combo sản phẩm giá trị cao: nếu combo có A, B, C thì tạo A sang B, C và tương tự.</p>
      {locked ? (
        <EmptyState icon={Lock} title="Chưa có combo để tạo gợi ý" text="Hãy chạy phân tích combo giá trị cao trước." />
      ) : rows.length ? (
        <DataTable rows={rows} />
      ) : (
        <EmptyState icon={ShoppingBasket} title="Chưa có gợi ý bán kèm" text="Combo hiện tại chưa đủ sản phẩm để sinh gợi ý." />
      )}
    </section>
  );
}

function SensitiveSection({
  comboSource,
  selectedKeys,
  setSelectedKeys
}: {
  comboSource: Dict[];
  selectedKeys: string[];
  setSelectedKeys: (keys: string[]) => void;
}) {
  function toggle(key: string) {
    setSelectedKeys(selectedKeys.includes(key) ? selectedKeys.filter((item) => item !== key) : [...selectedKeys, key]);
  }
  const rows = comboSource.map((row) => {
    const key = patternKey(row);
    return {
      key,
      combo: comboLabel(row),
      utility: formatNumber(readNumber(row, ["window_utility", "utility", "total_utility"], 0)),
      peak: peakWindow(row),
      peakness: formatNumber(readNumber(row, ["peakness_ratio"], 0), 2),
      reason:
        readNumber(row, ["peakness_ratio"], 0) >= 1.5
          ? "Tăng mạnh theo tháng và được hệ thống đánh dấu là mẫu nhạy cảm theo thời gian."
          : "Doanh thu đóng góp cao, nên cân nhắc bảo vệ khi chia sẻ dữ liệu."
    };
  });
  return (
    <section className="panel full">
      <div className="section-head">
        <div>
          <h2>Combo nhạy cảm cần bảo vệ</h2>
          <p>Một số combo có doanh thu cao hoặc tăng mạnh theo tháng có thể là tri thức kinh doanh nhạy cảm.</p>
        </div>
        <StatusBadge state={selectedKeys.length ? "done" : rows.length ? "ready" : "locked"} />
      </div>
      {rows.length ? (
        <div className="sensitive-list">
          {rows.map((row) => (
            <label className="sensitive-row" key={row.key}>
              <input type="checkbox" checked={selectedKeys.includes(row.key)} onChange={() => toggle(row.key)} />
              <span>
                <strong>{row.combo}</strong>
                <small>
                  Doanh thu {row.utility} • Peak {row.peak} • Mức nổi bật {row.peakness} • {row.reason}
                </small>
              </span>
            </label>
          ))}
        </div>
      ) : (
        <EmptyState icon={AlertTriangle} title="Chưa có combo nhạy cảm" text="Hãy chạy tìm combo hoặc tải kết quả đã phân tích." />
      )}
    </section>
  );
}

function ProtectSection({
  selectedCount,
  phase2,
  phase3,
  canProtect,
  canVerify,
  isProtecting,
  isVerifying,
  onProtect,
  onVerify
}: {
  selectedCount: number;
  phase2: Phase2Response | null;
  phase3: Phase3Response | null;
  canProtect: boolean;
  canVerify: boolean;
  isProtecting: boolean;
  isVerifying: boolean;
  onProtect: () => void;
  onVerify: () => void;
}) {
  const phase2Summary = phase2?.summary;
  const report = phase3?.report;
  const localLeaks = readNumber(report, ["local_violations", "local_violations_after_patch"], readNumber(phase2Summary, ["local_violations_after_patch", "local_violations_after"], 0));
  const globalLeaks = readNumber(report, ["global_leaks", "post_patch_global_leaks"], readNumber(phase2Summary, ["post_patch_global_leaks", "post_patch_leaks"], 0));
  const pass = Boolean(report?.PHASE3_PASS) || Boolean(phase2 && localLeaks === 0 && globalLeaks === 0);
  return (
    <div className="grid two">
      <section className="panel">
        <h2>Ẩn combo khỏi dữ liệu chia sẻ</h2>
        <p className="muted">Hệ thống điều chỉnh doanh thu đóng góp trong các hóa đơn liên quan để combo nhạy cảm không còn bị khai phá lại.</p>
        <div className="metric-grid compact">
          <Metric icon={AlertTriangle} label="Combo cần bảo vệ" value={formatNumber(selectedCount)} hint="Đã tick ở bước trước" />
          <Metric icon={ShieldCheck} label="Combo đã ẩn" value={formatNumber(readNumber(phase2Summary, ["sensitive_patterns"], 0))} hint="Sau khi chạy bảo vệ" />
          <Metric icon={FileText} label="Giao dịch bị chỉnh sửa" value={formatNumber(readNumber(phase2Summary, ["modified_transactions", "num_modified_transactions"], 0))} hint="Hóa đơn có thay đổi utility" />
          <Metric icon={Activity} label="Tỷ lệ mất giá trị dữ liệu" value={formatPercent(readNumber(phase2Summary, ["utility_loss_rate", "utility_loss_percent"], 0))} hint="Utility loss" />
        </div>
        <LoadingButton kind="primary" loading={isProtecting} disabled={!canProtect} onClick={onProtect}>
          <ShieldCheck size={18} />
          Ẩn các combo đã chọn
        </LoadingButton>
        {!selectedCount ? <p className="muted small">Chưa chọn combo cần bảo vệ. Hãy tick combo nhạy cảm trước khi ẩn dữ liệu.</p> : null}
      </section>
      <section className="panel">
        <h2>Kiểm tra an toàn dữ liệu sau xử lý</h2>
        <div className={pass ? "notice ok" : "notice warn"}>
          {pass
            ? "PASS - Dữ liệu đã được bảo vệ theo các tiêu chí kiểm chứng."
            : "WARNING - Vẫn còn mẫu nhạy cảm có thể bị khai phá lại hoặc chưa chạy kiểm chứng."}
        </div>
        <div className="metric-grid compact">
          <Metric icon={AlertCircle} label="Rò rỉ trong từng tháng" value={formatNumber(localLeaks)} hint="Local violations" />
          <Metric icon={AlertTriangle} label="Rò rỉ toàn cục" value={formatNumber(globalLeaks)} hint="Global leakage" />
          <Metric icon={Activity} label="Utility loss" value={formatPercent(readNumber(report, ["utility_loss_rate", "utility_loss_percent"], readNumber(phase2Summary, ["utility_loss_rate", "utility_loss_percent"], 0)))} hint="Mất giá trị dữ liệu" />
          <Metric icon={FileText} label="Modified transaction rate" value={formatPercent(readNumber(report, ["modified_transaction_rate"], 0))} hint="Tỷ lệ hóa đơn bị chỉnh" />
        </div>
        <LoadingButton kind="secondary" loading={isVerifying} disabled={!canVerify} onClick={onVerify}>
          <CheckCircle2 size={18} />
          Kiểm tra rò rỉ
        </LoadingButton>
      </section>
      <section className="panel full">
        <h2>Giao dịch đã chỉnh sửa</h2>
        <DataTable rows={phase2?.modified_transactions_preview ?? phase3?.modified_transactions_preview ?? []} />
      </section>
    </div>
  );
}

function ReportsSection({ runId, outputs, explorer, locked }: { runId: string; outputs: OutputFile[]; explorer: ExplorerResponse | null; locked: boolean }) {
  const recommended = [
    "phase2_sanitized_db.json",
    "phase2_summary.json",
    "phase1_peak_shui.json",
    "phase3_verification_report.json",
    "modified_transactions.csv",
    "phase3_window_metrics.csv",
    "phase3_pattern_metrics.csv"
  ];
  return (
    <div className="grid two">
      <section className="panel full">
        <h2>Xuất dữ liệu đã bảo vệ</h2>
        <p className="muted">Tải dữ liệu đã bảo vệ, danh sách combo, báo cáo ẩn combo và báo cáo kiểm chứng rò rỉ.</p>
        {locked ? (
          <EmptyState icon={Download} title="Chưa có báo cáo" text="Hãy hoàn tất bảo vệ dữ liệu và kiểm tra rò rỉ, hoặc tải bộ kết quả đã phân tích." />
        ) : (
          <div className="download-grid">
            {outputs.map((file) => (
              <a className={recommended.includes(file.file_name) ? "download important" : "download"} key={file.file_name} href={api.exportUrl(runId, file.file_name)}>
                <FileText size={18} />
                <span>{file.file_name}</span>
                <small>{file.size_bytes ? `${formatNumber(file.size_bytes)} bytes` : "output"}</small>
              </a>
            ))}
          </div>
        )}
      </section>
      <section className="panel">
        <h2>Combo nhạy cảm</h2>
        <DataTable rows={(explorer?.selected_patterns ?? []).slice(0, 20).map(mapComboRow)} />
      </section>
      <section className="panel">
        <h2>Kiểm chứng rò rỉ</h2>
        <DataTable rows={explorer?.window_metrics ?? []} />
      </section>
    </div>
  );
}

function AdvancedSection({
  presetKey,
  setPresetKey,
  showAdvanced,
  setShowAdvanced
}: {
  presetKey: PresetKey;
  setPresetKey: (key: PresetKey) => void;
  showAdvanced: boolean;
  setShowAdvanced: (value: boolean) => void;
}) {
  const preset = presets[presetKey];
  return (
    <section className="panel full">
      <div className="section-head">
        <div>
          <h2>Cấu hình nâng cao</h2>
          <p>Người dùng chính chỉ cần chọn preset. Thuật ngữ kỹ thuật được giữ ở khu vực này để phục vụ đồ án.</p>
        </div>
        <Settings2 size={22} />
      </div>
      <div className="notice warn">Tham số nâng cao ảnh hưởng đến thời gian khai phá và số lượng combo tìm được.</div>
      <div className="preset-grid">
        {(Object.keys(presets) as PresetKey[]).map((key) => (
          <button className={presetKey === key ? "preset-card active" : "preset-card"} key={key} onClick={() => setPresetKey(key)}>
            <strong>{presets[key].label}</strong>
            <span>{presets[key].help}</span>
            {presetKey === key ? <CheckCircle2 size={18} /> : <ChevronRight size={18} />}
          </button>
        ))}
      </div>
      <LoadingButton kind="secondary" onClick={() => setShowAdvanced(!showAdvanced)}>
        <Settings2 size={18} />
        {showAdvanced ? "Ẩn tùy chỉnh nâng cao" : "Mở tùy chỉnh nâng cao"}
      </LoadingButton>
      {showAdvanced ? (
        <div className="technical open">
          <DataTable
            rows={[
              { "Tham số": "max_transaction_len", "Giá trị": preset.max_transaction_len },
              { "Tham số": "mining_ratio", "Giá trị": preset.mining_ratio },
              { "Tham số": "sensitive_ratio", "Giá trị": preset.sensitive_ratio },
              { "Tham số": "candidate_mining_ratio", "Giá trị": preset.candidate_mining_ratio },
              { "Tham số": "min_peakness_ratio", "Giá trị": preset.min_peakness_ratio },
              { "Tham số": "min_support_windows", "Giá trị": preset.min_support_windows },
              { "Tham số": "max_selected_per_window", "Giá trị": preset.max_selected_per_window },
              { "Tham số": "max_patterns_per_window", "Giá trị": preset.max_patterns_per_window }
            ]}
          />
        </div>
      ) : null}
    </section>
  );
}

function UploadZone({
  title,
  description,
  accept,
  multiple,
  disabled,
  loading,
  onFiles
}: {
  title: string;
  description: string;
  accept: string;
  multiple?: boolean;
  disabled?: boolean;
  loading?: boolean;
  onFiles: (files: File[]) => void;
}) {
  const [dragging, setDragging] = useState(false);
  return (
    <label
      className={dragging ? "upload-zone dragging" : "upload-zone"}
      onDragOver={(event) => {
        event.preventDefault();
        if (!disabled) setDragging(true);
      }}
      onDragLeave={() => setDragging(false)}
      onDrop={(event) => {
        event.preventDefault();
        setDragging(false);
        if (!disabled) onFiles(Array.from(event.dataTransfer.files ?? []));
      }}
    >
      <div className="upload-icon">{loading ? <Loader2 className="spinner" size={24} /> : <Upload size={24} />}</div>
      <strong>{loading ? "Đang tải dữ liệu lên..." : title}</strong>
      <span>{description}</span>
      <small>{accept}</small>
      <input
        type="file"
        accept={accept}
        multiple={multiple}
        disabled={disabled}
        onChange={(event) => {
          const files = Array.from(event.target.files ?? []);
          if (files.length) onFiles(files);
          event.currentTarget.value = "";
        }}
      />
    </label>
  );
}

function LoadingButton({
  children,
  kind = "primary",
  loading,
  disabled,
  onClick
}: {
  children: ReactNode;
  kind?: "primary" | "secondary" | "danger" | "ghost";
  loading?: boolean;
  disabled?: boolean;
  onClick?: () => void;
}) {
  return (
    <button className={`${kind}-button`} disabled={disabled || loading} onClick={onClick}>
      {loading ? <Loader2 size={18} className="spinner" /> : null}
      {children}
    </button>
  );
}

function Metric({ icon: Icon, label, value, hint }: { icon: LucideIcon; label: string; value: string | number; hint: string }) {
  return (
    <div className="metric-card">
      <div className="metric-icon">
        <Icon size={18} />
      </div>
      <span>{label}</span>
      <strong>{value}</strong>
      <small>{hint}</small>
    </div>
  );
}

function DataTable({ rows }: { rows: Dict[] }) {
  if (!rows.length) return <EmptyState icon={FileText} title="Chưa có dữ liệu" text="Kết quả sẽ hiển thị ở đây sau khi hoàn tất bước tương ứng." />;
  const columns = Object.keys(rows[0]).filter((key) => key !== "key");
  return (
    <div className="table-card">
      <table className="data-table">
        <thead>
          <tr>
            {columns.map((column) => (
              <th key={column}>{column}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.slice(0, 80).map((row, index) => (
            <tr key={`${row.key ?? index}`}>
              {columns.map((column) => (
                <td className={isNumericCell(row[column]) ? "numeric" : ""} key={column}>{formatCell(row[column])}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function isNumericCell(value: unknown) {
  return typeof value === "number" || (typeof value === "string" && value !== "" && Number.isFinite(Number(value.replaceAll(".", "").replace(",", "."))));
}

function formatCell(value: unknown) {
  if (Array.isArray(value)) return value.join(", ");
  if (typeof value === "number") return formatNumber(value, Number.isInteger(value) ? 0 : 2);
  if (typeof value === "boolean") return value ? "Có" : "Không";
  if (value && typeof value === "object") return JSON.stringify(value);
  return String(value ?? "-");
}

function MiniBars({ rows, xKey, yKey }: { rows: Dict[]; xKey: string; yKey: string }) {
  if (!rows.length) return <EmptyState icon={BarChart3} title="Chưa có dữ liệu biểu đồ" text="Upload dữ liệu hoặc tải kết quả đã phân tích để xem chart." />;
  const values = rows.map((row) => readNumber(row, [yKey], 0));
  const max = Math.max(...values, 1);
  return (
    <div className="bars">
      {rows.slice(0, 18).map((row, index) => {
        const value = readNumber(row, [yKey], 0);
        return (
          <div className="bar-col" key={`${readText(row, [xKey], String(index))}-${index}`}>
            <span className="bar-value">{formatNumber(value)}</span>
            <div className="bar" style={{ height: `${Math.max(8, (value / max) * 120)}px` }} />
            <small>{readText(row, [xKey], "-")}</small>
          </div>
        );
      })}
    </div>
  );
}

function EmptyState({ icon: Icon, title, text }: { icon: LucideIcon; title: string; text: string }) {
  return (
    <div className="empty-state">
      <div className="empty-icon">
        <Icon size={24} />
      </div>
      <strong>{title}</strong>
      <span>{text}</span>
    </div>
  );
}
