"use client";

import { useCallback, useEffect, useState } from "react";
import { Navbar } from "@/components/navbar";
import { Footer } from "@/components/footer";
import { cn } from "@/lib/utils";
import {
  api,
  type BenchmarkReport,
  type KnowledgeOverview,
  type MetricsReport,
  type PromptInfo,
  type UxReport,
} from "@/lib/api";

const WINDOWS = [
  { hours: 24, label: "24h" },
  { hours: 168, label: "7d" },
  { hours: 0, label: "All time" },
];

// Benchmark metrics worth a headline card, in display order.
const QUALITY_CARDS: { metric: string; label: string; pct?: boolean }[] = [
  { metric: "overall", label: "Overall score", pct: true },
  { metric: "success", label: "Success rate", pct: true },
  { metric: "confidence", label: "Confidence", pct: true },
  { metric: "hallucination_rate", label: "Hallucination", pct: true },
  { metric: "repair_rate", label: "Repair rate", pct: true },
  { metric: "duration_ms", label: "Avg duration (ms)" },
];

function Card({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="rounded-lg border border-zinc-800 bg-zinc-900 overflow-hidden">
      <div className="px-4 py-3 border-b border-zinc-800">
        <span className="text-xs font-medium text-zinc-400 uppercase tracking-wider">
          {title}
        </span>
      </div>
      <div className="p-4">{children}</div>
    </div>
  );
}

function Empty({ hint }: { hint: string }) {
  return <p className="text-sm text-zinc-600 italic">{hint}</p>;
}

function Th({ children }: { children: React.ReactNode }) {
  return (
    <th className="text-left text-xs font-medium text-zinc-500 pb-2 pr-4">{children}</th>
  );
}

function Td({ children }: { children: React.ReactNode }) {
  return <td className="py-1.5 pr-4 text-sm text-zinc-300">{children}</td>;
}

export default function DashboardPage() {
  const [hours, setHours] = useState(24);
  const [metrics, setMetrics] = useState<MetricsReport | null>(null);
  const [benchmarks, setBenchmarks] = useState<BenchmarkReport | null>(null);
  const [ux, setUx] = useState<UxReport | null>(null);
  const [prompts, setPrompts] = useState<PromptInfo[]>([]);
  const [knowledge, setKnowledge] = useState<KnowledgeOverview | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async (h: number) => {
    // No synchronous setState here — everything lands after the await, which
    // keeps react-hooks/set-state-in-effect happy when effects call this.
    const results = await Promise.allSettled([
      api.metrics(h),
      api.benchmarks(h),
      api.ux(h),
      api.prompts(),
      api.knowledgeOverview(),
    ] as const);
    const [m, b, u, p, k] = results;
    if (m.status === "fulfilled") setMetrics(m.value);
    if (b.status === "fulfilled") setBenchmarks(b.value);
    if (u.status === "fulfilled") setUx(u.value);
    if (p.status === "fulfilled") setPrompts(p.value.prompts);
    if (k.status === "fulfilled") setKnowledge(k.value);
    setError(
      results.every((r) => r.status === "rejected")
        ? "Could not reach the API — is the backend running on port 8000?"
        : null
    );
    setLoading(false);
  }, []);

  useEffect(() => {
    // Fetch-on-mount/window-change. All setState in load() happens after the
    // await (no sync cascade); the rule can't see through the async boundary.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void load(hours);
  }, [hours, load]);

  const benchByName = new Map(
    (benchmarks?.metrics ?? []).map((m) => [m.metric, m])
  );

  return (
    <>
      <Navbar />
      <main className="flex-1 mx-auto w-full max-w-7xl px-4 sm:px-6 lg:px-8 py-10">
        <div className="mb-8 flex flex-wrap items-center justify-between gap-4">
          <div>
            <h1 className="text-2xl font-bold text-white">SiloLoop Dashboard</h1>
            <p className="text-zinc-400 mt-1 text-sm">
              What the engine is doing, how well it&apos;s doing it, and what it has learned.
            </p>
          </div>
          <div className="flex items-center gap-2">
            {WINDOWS.map((w) => (
              <button
                key={w.hours}
                onClick={() => {
                  setLoading(true);
                  setHours(w.hours);
                }}
                className={cn(
                  "rounded px-3 py-1 text-sm transition-colors border",
                  hours === w.hours
                    ? "bg-teal-500/20 border-teal-500/50 text-teal-400"
                    : "border-zinc-700 text-zinc-400 hover:border-zinc-500"
                )}
              >
                {w.label}
              </button>
            ))}
            <button
              onClick={() => {
                setLoading(true);
                void load(hours);
              }}
              className="rounded px-3 py-1 text-sm border border-zinc-700 text-zinc-400 hover:border-zinc-500 transition-colors"
            >
              {loading ? "Loading…" : "Refresh"}
            </button>
          </div>
        </div>

        {error && (
          <div className="mb-6 rounded-md border border-red-500/30 bg-red-500/10 p-3 text-sm text-red-400">
            {error}
          </div>
        )}

        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 items-start">
          {/* Quality — benchmark headline cards */}
          <Card title="Quality (benchmarked runs)">
            {benchByName.size === 0 ? (
              <Empty hint="No benchmark data yet — run a request with benchmark=true." />
            ) : (
              <div className="grid grid-cols-2 sm:grid-cols-3 gap-3">
                {QUALITY_CARDS.filter((c) => benchByName.has(c.metric)).map((c) => {
                  const m = benchByName.get(c.metric)!;
                  return (
                    <div
                      key={c.metric}
                      className="rounded-md border border-zinc-800 bg-zinc-950 p-3"
                    >
                      <div className="text-xs text-zinc-500">{c.label}</div>
                      <div className="text-xl font-semibold text-white mt-1">
                        {c.pct ? `${Math.round(m.avg * 100)}%` : Math.round(m.avg)}
                      </div>
                      <div className="text-[11px] text-zinc-600 mt-0.5">
                        n={m.count} · min {c.pct ? Math.round(m.min * 100) : Math.round(m.min)}
                        {c.pct ? "%" : ""} · max{" "}
                        {c.pct ? Math.round(m.max * 100) : Math.round(m.max)}
                        {c.pct ? "%" : ""}
                      </div>
                    </div>
                  );
                })}
              </div>
            )}
          </Card>

          {/* Runs */}
          <Card title="Runs">
            {!metrics || metrics.runs.length === 0 ? (
              <Empty hint="No runs recorded in this window yet." />
            ) : (
              <table className="w-full">
                <thead>
                  <tr>
                    <Th>Kind</Th>
                    <Th>Status</Th>
                    <Th>Count</Th>
                    <Th>Avg ms</Th>
                  </tr>
                </thead>
                <tbody>
                  {metrics.runs.map((r) => (
                    <tr key={`${r.kind}-${r.status}`}>
                      <Td>{r.kind}</Td>
                      <Td>
                        <span
                          className={
                            r.status === "ok" ? "text-teal-400" : "text-red-400"
                          }
                        >
                          {r.status}
                        </span>
                      </Td>
                      <Td>{r.count}</Td>
                      <Td>{r.avg_duration_ms ?? "—"}</Td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </Card>

          {/* LLM usage */}
          <Card title="LLM usage (via Model Router)">
            {!metrics || metrics.llm.length === 0 ? (
              <Empty hint="No LLM calls in this window yet." />
            ) : (
              <table className="w-full">
                <thead>
                  <tr>
                    <Th>Agent</Th>
                    <Th>Model</Th>
                    <Th>Calls</Th>
                    <Th>Tokens</Th>
                  </tr>
                </thead>
                <tbody>
                  {metrics.llm.map((l, i) => (
                    <tr key={i}>
                      <Td>{l.agent ?? "—"}</Td>
                      <Td>{l.model ?? "—"}</Td>
                      <Td>{l.count}</Td>
                      <Td>{l.total_tokens}</Td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </Card>

          {/* Knowledge */}
          <Card title="Knowledge graph">
            {!knowledge ||
            Object.keys(knowledge.entities).length === 0 ? (
              <Empty hint="Nothing learned yet — run an extract with loop=true." />
            ) : (
              <div className="space-y-4">
                <div className="flex flex-wrap gap-2">
                  {Object.entries(knowledge.entities).map(([type, count]) => (
                    <span
                      key={type}
                      className="rounded border border-zinc-700 px-2.5 py-1 text-sm text-zinc-300"
                    >
                      {type}: <span className="text-white font-medium">{count}</span>
                    </span>
                  ))}
                </div>
                {knowledge.top_domains.length > 0 && (
                  <div>
                    <div className="text-xs text-zinc-500 mb-1.5">Top domains (pages known)</div>
                    {knowledge.top_domains.map((d) => (
                      <div key={d.domain} className="flex justify-between text-sm py-0.5">
                        <span className="text-zinc-300">{d.domain}</span>
                        <span className="text-zinc-500">{d.pages}</span>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            )}
          </Card>

          {/* Learned strategies */}
          <Card title="Learned fetch strategies">
            {!knowledge || knowledge.strategies.length === 0 ? (
              <Empty hint="No strategies learned yet — the retry engine records them per domain." />
            ) : (
              <table className="w-full">
                <thead>
                  <tr>
                    <Th>Domain</Th>
                    <Th>Strategy</Th>
                    <Th>Success</Th>
                    <Th>Latency</Th>
                  </tr>
                </thead>
                <tbody>
                  {knowledge.strategies.map((s) => (
                    <tr key={s.domain}>
                      <Td>{s.domain}</Td>
                      <Td>
                        <span className="text-teal-400">{s.strategy}</span>
                      </Td>
                      <Td>{Math.round(s.success_rate * 100)}%</Td>
                      <Td>{s.avg_latency_ms ? `${Math.round(s.avg_latency_ms)} ms` : "—"}</Td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </Card>

          {/* Prompts */}
          <Card title="Prompt versions">
            {prompts.length === 0 ? (
              <Empty hint="Prompts seed on first LLM call; publish new versions via PUT /v1/prompts." />
            ) : (
              <table className="w-full">
                <thead>
                  <tr>
                    <Th>Agent</Th>
                    <Th>Name</Th>
                    <Th>Version</Th>
                    <Th>Active</Th>
                  </tr>
                </thead>
                <tbody>
                  {prompts.map((p) => (
                    <tr key={`${p.agent}-${p.name}-${p.version}`}>
                      <Td>{p.agent}</Td>
                      <Td>{p.name}</Td>
                      <Td>v{p.version}</Td>
                      <Td>
                        {p.active ? (
                          <span className="text-teal-400">active</span>
                        ) : (
                          <span className="text-zinc-600">—</span>
                        )}
                      </Td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </Card>

          {/* UX report */}
          <Card title="Frontend UX report">
            {!ux ? (
              <Empty hint="No UX telemetry yet — use the playground and check back." />
            ) : (
              <div className="space-y-4">
                <div className="grid grid-cols-3 gap-3">
                  <div className="rounded-md border border-zinc-800 bg-zinc-950 p-3">
                    <div className="text-xs text-zinc-500">Avg wait</div>
                    <div className="text-xl font-semibold text-white mt-1">
                      {ux.avg_wait_ms !== null ? `${Math.round(ux.avg_wait_ms)} ms` : "—"}
                    </div>
                  </div>
                  <div className="rounded-md border border-zinc-800 bg-zinc-950 p-3">
                    <div className="text-xs text-zinc-500">Error rate</div>
                    <div className="text-xl font-semibold text-white mt-1">
                      {Math.round(ux.error_rate * 100)}%
                    </div>
                  </div>
                  <div className="rounded-md border border-zinc-800 bg-zinc-950 p-3">
                    <div className="text-xs text-zinc-500">Abandon rate</div>
                    <div className="text-xl font-semibold text-white mt-1">
                      {Math.round(ux.abandon_rate * 100)}%
                    </div>
                  </div>
                </div>
                <div>
                  <div className="text-xs text-zinc-500 mb-1.5">Recommendations</div>
                  <ul className="space-y-1">
                    {ux.recommendations.map((r) => (
                      <li key={r} className="text-sm text-zinc-300">
                        • {r}
                      </li>
                    ))}
                  </ul>
                </div>
              </div>
            )}
          </Card>
        </div>
      </main>
      <Footer />
    </>
  );
}
