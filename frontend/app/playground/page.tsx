"use client";

import { useEffect, useRef, useState } from "react";
import { Navbar } from "@/components/navbar";
import { Footer } from "@/components/footer";
import { cn } from "@/lib/utils";
import { api, type ScrapeFormat } from "@/lib/api";
import { flushNow, track } from "@/lib/telemetry";

type Endpoint = "scrape" | "map" | "extract" | "crawl";

const ENDPOINTS: { id: Endpoint; label: string; description: string }[] = [
  { id: "scrape", label: "Scrape", description: "Fetch a URL and return clean content" },
  { id: "map", label: "Map", description: "Discover all URLs on a domain" },
  { id: "extract", label: "Extract", description: "LLM-powered structured extraction" },
  { id: "crawl", label: "Crawl", description: "Recursively crawl a site" },
];

const DEFAULT_SCHEMA = JSON.stringify(
  {
    type: "object",
    properties: {
      title: { type: "string" },
      summary: { type: "string" },
      main_topics: { type: "array", items: { type: "string" } },
    },
  },
  null,
  2
);

export default function PlaygroundPage() {
  const [endpoint, setEndpoint] = useState<Endpoint>("scrape");
  const [url, setUrl] = useState("https://example.com");
  const [formats, setFormats] = useState<ScrapeFormat[]>(["markdown"]);
  const [renderJs, setRenderJs] = useState(false);
  const [schema, setSchema] = useState(DEFAULT_SCHEMA);
  const [prompt, setPrompt] = useState("");
  const [maxPages, setMaxPages] = useState(10);
  const [maxDepth, setMaxDepth] = useState(2);
  const [includePaths, setIncludePaths] = useState("");
  const [excludePaths, setExcludePaths] = useState("");
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const [result, setResult] = useState<any>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [jobId, setJobId] = useState<string | null>(null);
  const [polling, setPolling] = useState(false);
  const [copied, setCopied] = useState(false);

  // UX telemetry: report abandons (tab hidden while a request is in flight).
  const pendingRef = useRef<Endpoint | null>(null);
  useEffect(() => {
    const onHide = () => {
      if (document.visibilityState === "hidden" && pendingRef.current) {
        track("playground.abandon", undefined, { endpoint: pendingRef.current });
        flushNow(true); // beacon — survives the page going away
      }
    };
    document.addEventListener("visibilitychange", onHide);
    return () => document.removeEventListener("visibilitychange", onHide);
  }, []);

  const toggleFormat = (f: ScrapeFormat) => {
    setFormats((prev) =>
      prev.includes(f) ? prev.filter((x) => x !== f) : [...prev, f]
    );
  };

  const pollJob = async (id: string) => {
    setPolling(true);
    const interval = setInterval(async () => {
      try {
        const status = await api.crawlStatus(id);
        setResult(status);
        if (status.status === "completed" || status.status === "failed") {
          clearInterval(interval);
          setPolling(false);
        }
      } catch (e) {
        clearInterval(interval);
        setPolling(false);
        setError(String(e));
      }
    }, 2000);
  };

  const run = async () => {
    setLoading(true);
    setError(null);
    setResult(null);
    setJobId(null);
    const startedAt = performance.now();
    track("playground.request", undefined, { endpoint });
    pendingRef.current = endpoint;

    try {
      if (endpoint === "scrape") {
        const res = await api.scrape({ url, formats, render_js: renderJs });
        setResult(res);
      } else if (endpoint === "map") {
        const res = await api.map({ url });
        setResult(res);
      } else if (endpoint === "extract") {
        let parsed;
        try {
          parsed = JSON.parse(schema);
        } catch {
          throw new Error("Invalid JSON schema");
        }
        const res = await api.extract({
          url,
          schema: parsed,
          prompt: prompt || undefined,
          render_js: renderJs,
        });
        setResult(res);
      } else if (endpoint === "crawl") {
        const res = await api.crawl({
          url,
          max_pages: maxPages,
          max_depth: maxDepth,
          formats,
          render_js: renderJs,
          include_paths: includePaths ? includePaths.split(",").map((s) => s.trim()) : undefined,
          exclude_paths: excludePaths ? excludePaths.split(",").map((s) => s.trim()) : undefined,
        });
        setJobId(res.id);
        setResult(res);
        pollJob(res.id);
      }
    } catch (e) {
      setError(String(e));
      track("playground.error", undefined, {
        endpoint,
        message: String(e).slice(0, 200),
      });
    } finally {
      track("playground.wait", Math.round(performance.now() - startedAt), { endpoint });
      pendingRef.current = null;
      setLoading(false);
    }
  };

  const resultStr = result
    ? JSON.stringify(
        result.screenshot
          ? { ...result, screenshot: "[base64 PNG — previewed above]" }
          : result,
        null,
        2
      )
    : null;

  return (
    <>
      <Navbar />
      <main className="flex-1 mx-auto w-full max-w-7xl px-4 sm:px-6 lg:px-8 py-10">
        <div className="mb-8">
          <h1 className="text-2xl font-bold text-white">Playground</h1>
          <p className="text-zinc-400 mt-1 text-sm">
            Test SiloCrawl endpoints live against your local API server.
          </p>
        </div>

        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 items-start">
          {/* Left — Controls */}
          <div className="space-y-5">
            {/* Endpoint selector */}
            <div className="rounded-lg border border-zinc-800 bg-zinc-900 overflow-hidden">
              <div className="px-4 py-3 border-b border-zinc-800">
                <span className="text-xs font-medium text-zinc-400 uppercase tracking-wider">Endpoint</span>
              </div>
              <div className="p-4 grid grid-cols-2 gap-2">
                {ENDPOINTS.map((e) => (
                  <button
                    key={e.id}
                    onClick={() => setEndpoint(e.id)}
                    className={cn(
                      "rounded-md px-3 py-2.5 text-left transition-colors",
                      endpoint === e.id
                        ? "bg-teal-500/20 border border-teal-500/50 text-teal-400"
                        : "border border-zinc-800 text-zinc-400 hover:border-zinc-600 hover:text-zinc-200"
                    )}
                  >
                    <div className="text-sm font-medium">{e.label}</div>
                    <div className="text-xs mt-0.5 opacity-70">{e.description}</div>
                  </button>
                ))}
              </div>
            </div>

            {/* URL */}
            <div className="rounded-lg border border-zinc-800 bg-zinc-900 overflow-hidden">
              <div className="px-4 py-3 border-b border-zinc-800">
                <span className="text-xs font-medium text-zinc-400 uppercase tracking-wider">URL</span>
              </div>
              <div className="p-4">
                <input
                  type="url"
                  value={url}
                  onChange={(e) => setUrl(e.target.value)}
                  placeholder="https://example.com"
                  className="w-full rounded-md border border-zinc-700 bg-zinc-950 px-3 py-2 text-sm text-white placeholder-zinc-500 focus:outline-none focus:border-teal-500 transition-colors"
                />
              </div>
            </div>

            {/* Options based on endpoint */}
            {(endpoint === "scrape" || endpoint === "crawl") && (
              <div className="rounded-lg border border-zinc-800 bg-zinc-900 overflow-hidden">
                <div className="px-4 py-3 border-b border-zinc-800">
                  <span className="text-xs font-medium text-zinc-400 uppercase tracking-wider">Formats</span>
                </div>
                <div className="p-4 flex flex-wrap gap-2">
                  {(["markdown", "html", "text", "links", "screenshot"] as ScrapeFormat[]).map((f) => (
                    <button
                      key={f}
                      onClick={() => toggleFormat(f)}
                      className={cn(
                        "rounded px-3 py-1 text-sm transition-colors border",
                        formats.includes(f)
                          ? "bg-teal-500/20 border-teal-500/50 text-teal-400"
                          : "border-zinc-700 text-zinc-400 hover:border-zinc-500"
                      )}
                    >
                      {f}
                    </button>
                  ))}
                </div>
              </div>
            )}

            {endpoint === "extract" && (
              <div className="space-y-4">
                <div className="rounded-lg border border-zinc-800 bg-zinc-900 overflow-hidden">
                  <div className="px-4 py-3 border-b border-zinc-800">
                    <span className="text-xs font-medium text-zinc-400 uppercase tracking-wider">JSON Schema</span>
                  </div>
                  <div className="p-4">
                    <textarea
                      value={schema}
                      onChange={(e) => setSchema(e.target.value)}
                      rows={8}
                      className="w-full rounded-md border border-zinc-700 bg-zinc-950 px-3 py-2 text-sm text-zinc-200 font-mono placeholder-zinc-500 focus:outline-none focus:border-teal-500 transition-colors resize-none"
                    />
                  </div>
                </div>
                <div className="rounded-lg border border-zinc-800 bg-zinc-900 overflow-hidden">
                  <div className="px-4 py-3 border-b border-zinc-800">
                    <span className="text-xs font-medium text-zinc-400 uppercase tracking-wider">Prompt (optional)</span>
                  </div>
                  <div className="p-4">
                    <input
                      type="text"
                      value={prompt}
                      onChange={(e) => setPrompt(e.target.value)}
                      placeholder="e.g. Extract the article title and main topics"
                      className="w-full rounded-md border border-zinc-700 bg-zinc-950 px-3 py-2 text-sm text-white placeholder-zinc-500 focus:outline-none focus:border-teal-500 transition-colors"
                    />
                  </div>
                </div>
              </div>
            )}

            {endpoint === "crawl" && (
              <div className="rounded-lg border border-zinc-800 bg-zinc-900 overflow-hidden">
                <div className="px-4 py-3 border-b border-zinc-800">
                  <span className="text-xs font-medium text-zinc-400 uppercase tracking-wider">Crawl options</span>
                </div>
                <div className="p-4 space-y-4">
                  <div className="grid grid-cols-2 gap-4">
                    <div>
                      <label className="block text-xs text-zinc-400 mb-1.5">Max pages</label>
                      <input
                        type="number"
                        value={maxPages}
                        onChange={(e) => setMaxPages(Number(e.target.value))}
                        min={1}
                        max={100}
                        className="w-full rounded-md border border-zinc-700 bg-zinc-950 px-3 py-2 text-sm text-white focus:outline-none focus:border-teal-500 transition-colors"
                      />
                    </div>
                    <div>
                      <label className="block text-xs text-zinc-400 mb-1.5">Max depth</label>
                      <input
                        type="number"
                        value={maxDepth}
                        onChange={(e) => setMaxDepth(Number(e.target.value))}
                        min={1}
                        max={10}
                        className="w-full rounded-md border border-zinc-700 bg-zinc-950 px-3 py-2 text-sm text-white focus:outline-none focus:border-teal-500 transition-colors"
                      />
                    </div>
                  </div>
                  <div>
                    <label className="block text-xs text-zinc-400 mb-1.5">
                      Include paths <span className="text-zinc-600">(regex, comma-separated)</span>
                    </label>
                    <input
                      type="text"
                      value={includePaths}
                      onChange={(e) => setIncludePaths(e.target.value)}
                      placeholder="e.g. /sport/cricket/articles"
                      className="w-full rounded-md border border-zinc-700 bg-zinc-950 px-3 py-2 text-sm text-white placeholder-zinc-600 focus:outline-none focus:border-teal-500 transition-colors"
                    />
                  </div>
                  <div>
                    <label className="block text-xs text-zinc-400 mb-1.5">
                      Exclude paths <span className="text-zinc-600">(regex, comma-separated)</span>
                    </label>
                    <input
                      type="text"
                      value={excludePaths}
                      onChange={(e) => setExcludePaths(e.target.value)}
                      placeholder="e.g. /live, /scores"
                      className="w-full rounded-md border border-zinc-700 bg-zinc-950 px-3 py-2 text-sm text-white placeholder-zinc-600 focus:outline-none focus:border-teal-500 transition-colors"
                    />
                  </div>
                </div>
              </div>
            )}

            {(endpoint === "scrape" || endpoint === "extract" || endpoint === "crawl") && (
              <label className="flex items-center gap-2 cursor-pointer">
                <input
                  type="checkbox"
                  checked={renderJs}
                  onChange={(e) => setRenderJs(e.target.checked)}
                  className="rounded border-zinc-600 bg-zinc-800 text-teal-500 focus:ring-teal-500"
                />
                <span className="text-sm text-zinc-400">Render JavaScript (Playwright)</span>
              </label>
            )}

            <button
              onClick={run}
              disabled={loading || !url}
              className="w-full rounded-md bg-teal-500 py-2.5 text-sm font-semibold text-white hover:bg-teal-600 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
            >
              {loading ? "Running…" : `Run /v1/${endpoint}`}
            </button>
          </div>

          {/* Right — Output */}
          <div className="rounded-lg border border-zinc-800 bg-zinc-900 overflow-hidden min-h-[400px]">
            <div className="flex items-center justify-between px-4 py-3 border-b border-zinc-800">
              <span className="text-xs font-medium text-zinc-400 uppercase tracking-wider">Response</span>
              <div className="flex items-center gap-3">
              {polling && (
                <span className="flex items-center gap-1.5 text-xs text-teal-400">
                  <span className="h-1.5 w-1.5 rounded-full bg-teal-400 animate-pulse" />
                  Polling job {jobId?.slice(0, 8)}…
                </span>
              )}
              {result && !polling && (
                <span className="text-xs text-teal-400">Done</span>
              )}
              {resultStr && (
                <button
                  onClick={async () => {
                    await navigator.clipboard.writeText(resultStr);
                    setCopied(true);
                    setTimeout(() => setCopied(false), 2000);
                  }}
                  className="text-xs text-zinc-400 hover:text-white transition-colors"
                >
                  {copied ? "Copied!" : "Copy all"}
                </button>
              )}
              </div>
            </div>

            <div className="p-4 h-full">
              {error && (
                <div className="rounded-md border border-red-500/30 bg-red-500/10 p-3 text-sm text-red-400">
                  {error}
                </div>
              )}
              {!result && !error && !loading && (
                <p className="text-sm text-zinc-600 italic">
                  Configure a request and click Run to see the response.
                </p>
              )}
              {loading && !result && (
                <p className="text-sm text-zinc-500 animate-pulse">Waiting for response…</p>
              )}
              {result?.screenshot && (
                // eslint-disable-next-line @next/next/no-img-element
                <img
                  src={`data:image/png;base64,${result.screenshot}`}
                  alt="Page screenshot"
                  className="mb-4 max-h-[400px] w-auto rounded-md border border-zinc-800"
                />
              )}
              {resultStr && (
                <pre className="text-xs font-mono text-zinc-300 overflow-auto max-h-[600px] leading-relaxed whitespace-pre-wrap">
                  {resultStr}
                </pre>
              )}
            </div>
          </div>
        </div>
      </main>
      <Footer />
    </>
  );
}
