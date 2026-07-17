const BASE_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
const API_KEY = process.env.NEXT_PUBLIC_API_KEY;

function authHeaders(): Record<string, string> {
  return API_KEY ? { Authorization: `Bearer ${API_KEY}` } : {};
}

export type ScrapeFormat = "markdown" | "html" | "text" | "links" | "screenshot";

export interface ScrapeRequest {
  url: string;
  formats?: ScrapeFormat[];
  render_js?: boolean;
}

export interface ScrapeResult {
  markdown?: string;
  html?: string;
  text?: string;
  links?: string[];
  screenshot?: string; // base64 PNG
  metadata: {
    title?: string;
    description?: string;
    source_url?: string;
    status_code?: number;
  };
}

export interface MapRequest {
  url: string;
  limit?: number;
}

export interface MapResult {
  base_url: string;
  links: string[];
  count: number;
}

export interface ExtractRequest {
  url?: string;
  content?: string;
  schema: Record<string, unknown>;
  prompt?: string;
  render_js?: boolean;
}

export interface ExtractResult {
  data: Record<string, unknown>;
  source_url?: string;
}

export interface CrawlRequest {
  url: string;
  max_pages?: number;
  max_depth?: number;
  formats?: ScrapeFormat[];
  render_js?: boolean;
  include_paths?: string[];
  exclude_paths?: string[];
}

export interface CrawlJobStatus {
  id: string;
  status: "queued" | "running" | "completed" | "failed";
  total: number;
  completed: number;
  data: ScrapeResult[];
  failed_pages: { url: string; error: string }[];
  error?: string;
}

// ---------- SiloLoop dashboard (INC-B13) ----------

export interface MetricsReport {
  window_hours: number;
  runs: { kind: string; status: string; count: number; avg_duration_ms?: number | null }[];
  llm: { agent?: string | null; model?: string | null; count: number; total_tokens: number }[];
  crawl_jobs: { status: string; count: number }[];
}

export interface BenchmarkReport {
  window_hours: number;
  metrics: { metric: string; avg: number; min: number; max: number; count: number }[];
  recent: { metric: string; value: number; run_id?: string | null; created_at?: string | null }[];
}

export interface UxReport {
  window_hours: number;
  events: Record<string, number>;
  avg_wait_ms: number | null;
  error_rate: number;
  abandon_rate: number;
  recommendations: string[];
}

export interface PromptInfo {
  agent: string;
  name: string;
  version: number;
  active: boolean;
  template: string;
  created_at?: string | null;
}

export interface KnowledgeOverview {
  entities: Record<string, number>;
  top_domains: { domain: string; pages: number }[];
  strategies: {
    domain: string;
    strategy: string;
    success_rate: number;
    avg_latency_ms: number | null;
  }[];
}

async function get<T>(path: string): Promise<T> {
  const res = await fetch(`${BASE_URL}${path}`, { headers: authHeaders() });
  if (!res.ok) throw new Error(`${res.status}: ${await res.text()}`);
  return res.json();
}

async function post<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(`${BASE_URL}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...authHeaders() },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`${res.status}: ${text}`);
  }
  return res.json();
}

export const api = {
  scrape: (req: ScrapeRequest) => post<ScrapeResult>("/v1/scrape", req),
  map: (req: MapRequest) => post<MapResult>("/v1/map", req),
  extract: (req: ExtractRequest) => post<ExtractResult>("/v1/extract", req),
  crawl: (req: CrawlRequest) => post<CrawlJobStatus>("/v1/crawl", req),
  crawlStatus: async (jobId: string): Promise<CrawlJobStatus> => {
    const res = await fetch(`${BASE_URL}/v1/crawl/${jobId}`, {
      headers: authHeaders(),
    });
    if (!res.ok) throw new Error(`${res.status}`);
    return res.json();
  },
  // SiloLoop dashboard feeds
  metrics: (hours: number) => get<MetricsReport>(`/metrics?hours=${hours}`),
  benchmarks: (hours: number) => get<BenchmarkReport>(`/v1/benchmarks?hours=${hours}`),
  ux: (hours: number) => get<UxReport>(`/v1/ux?hours=${hours}`),
  prompts: () => get<{ prompts: PromptInfo[] }>("/v1/prompts"),
  knowledgeOverview: () => get<KnowledgeOverview>("/v1/knowledge"),
};
