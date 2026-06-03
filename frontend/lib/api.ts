const BASE_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export type ScrapeFormat = "markdown" | "html" | "text" | "links";

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

async function post<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(`${BASE_URL}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
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
    const res = await fetch(`${BASE_URL}/v1/crawl/${jobId}`);
    if (!res.ok) throw new Error(`${res.status}`);
    return res.json();
  },
};
