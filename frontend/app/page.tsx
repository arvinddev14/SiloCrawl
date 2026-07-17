import Link from "next/link";
import { Navbar } from "@/components/navbar";
import { Footer } from "@/components/footer";
import { TabCodeBlock } from "@/components/code-block";

const SCRAPE_TABS = [
  {
    label: "Python",
    language: "python",
    code: `import httpx

resp = httpx.post("http://localhost:8000/v1/scrape", json={
    "url": "https://example.com",
    "formats": ["markdown"]
})
print(resp.json()["markdown"])`,
  },
  {
    label: "cURL",
    language: "bash",
    code: `curl -X POST http://localhost:8000/v1/scrape \\
  -H "content-type: application/json" \\
  -d '{"url": "https://example.com", "formats": ["markdown"]}'`,
  },
];

const EXTRACT_TABS = [
  {
    label: "Python",
    language: "python",
    code: `import httpx

resp = httpx.post("http://localhost:8000/v1/extract", json={
    "url": "https://example.com",
    "json_schema": {
        "type": "object",
        "properties": {
            "title": {"type": "string"},
            "summary": {"type": "string"}
        }
    }
})
print(resp.json()["data"])`,
  },
  {
    label: "cURL",
    language: "bash",
    code: `curl -X POST http://localhost:8000/v1/extract \\
  -H "content-type: application/json" \\
  -d '{
    "url": "https://example.com",
    "json_schema": {
      "type": "object",
      "properties": {
        "title": {"type": "string"},
        "summary": {"type": "string"}
      }
    }
  }'`,
  },
];

const CRAWL_TABS = [
  {
    label: "Python",
    language: "python",
    code: `import httpx, time

job = httpx.post("http://localhost:8000/v1/crawl", json={
    "url": "https://example.com",
    "max_pages": 20,
    "max_depth": 2,
    "formats": ["markdown"]
}).json()

while True:
    status = httpx.get(
        f"http://localhost:8000/v1/crawl/{job['id']}"
    ).json()
    if status["status"] in ("completed", "failed"):
        break
    time.sleep(2)

print(f"Crawled {len(status.get('data', []))} pages")`,
  },
  {
    label: "cURL",
    language: "bash",
    code: `# Start crawl
curl -X POST http://localhost:8000/v1/crawl \\
  -H "content-type: application/json" \\
  -d '{"url": "https://example.com", "max_pages": 20}'

# Poll status
curl http://localhost:8000/v1/crawl/<job_id>`,
  },
];

const MAP_TABS = [
  {
    label: "Python",
    language: "python",
    code: `import httpx

resp = httpx.post("http://localhost:8000/v1/map", json={
    "url": "https://example.com",
    "limit": 100
})
print(resp.json()["links"])`,
  },
  {
    label: "cURL",
    language: "bash",
    code: `curl -X POST http://localhost:8000/v1/map \\
  -H "content-type: application/json" \\
  -d '{"url": "https://example.com", "limit": 100}'`,
  },
];

const features = [
  {
    id: "scrape",
    icon: "⚡",
    title: "Scrape",
    description:
      "Fetch any URL and get back clean Markdown, HTML, text, or links. Optional JavaScript rendering for SPAs and dynamic pages.",
    tabs: SCRAPE_TABS,
  },
  {
    id: "extract",
    icon: "🧠",
    title: "Extract",
    description:
      "Supply a JSON Schema and get back structured data extracted by an LLM. Zero prompt engineering required.",
    tabs: EXTRACT_TABS,
  },
  {
    id: "crawl",
    icon: "🕷️",
    title: "Crawl",
    description:
      "Recursively follow links across a site with configurable depth and page limits. Jobs run asynchronously via Redis.",
    tabs: CRAWL_TABS,
  },
  {
    id: "map",
    icon: "🗺️",
    title: "Map",
    description:
      "Instantly discover every URL on a domain by combining sitemap.xml parsing and link extraction.",
    tabs: MAP_TABS,
  },
];

const stats = [
  { value: "4", label: "API endpoints" },
  { value: "Free", label: "Self-hosted" },
  { value: "LLM", label: "AI-powered extraction" },
  { value: "async", label: "Redis-backed crawl queue" },
];

export default function Home() {
  return (
    <>
      <Navbar />
      <main className="flex-1">
        {/* Hero */}
        <section className="relative overflow-hidden border-b border-zinc-800">
          <div className="absolute inset-0 bg-[radial-gradient(ellipse_80%_50%_at_50%_-20%,rgba(20,184,166,0.12),transparent)]" />
          <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8 py-24 md:py-36 relative">
            <div className="text-center max-w-3xl mx-auto">
              <div className="inline-flex items-center gap-2 rounded-full border border-teal-500/30 bg-teal-500/10 px-3 py-1 text-xs text-teal-400 mb-6">
                <span className="h-1.5 w-1.5 rounded-full bg-teal-400 animate-pulse" />
                Open source · Self-hosted
              </div>
              <h1 className="text-4xl md:text-6xl font-bold tracking-tight text-white mb-6">
                Power your AI agents with{" "}
                <span className="text-teal-500">clean web data</span>
              </h1>
              <p className="text-lg text-zinc-400 mb-10 max-w-2xl mx-auto">
                SiloCrawl is an open-source web scraping API. Scrape pages to Markdown,
                crawl entire sites, map URLs, and extract structured data using an LLM —
                all from a single self-hosted service.
              </p>
              <div className="flex flex-col sm:flex-row items-center justify-center gap-3">
                <Link
                  href="/playground"
                  className="w-full sm:w-auto rounded-md bg-teal-500 px-6 py-2.5 text-sm font-semibold text-white hover:bg-teal-600 transition-colors"
                >
                  Try the playground
                </Link>
                <Link
                  href="/docs"
                  className="w-full sm:w-auto rounded-md border border-zinc-700 px-6 py-2.5 text-sm font-semibold text-zinc-300 hover:border-zinc-500 hover:text-white transition-colors"
                >
                  Read the docs
                </Link>
              </div>
            </div>
          </div>
        </section>

        {/* Stats */}
        <section className="border-b border-zinc-800 bg-zinc-900/40">
          <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8 py-10">
            <dl className="grid grid-cols-2 md:grid-cols-4 gap-8">
              {stats.map((s) => (
                <div key={s.label} className="text-center">
                  <dt className="text-2xl font-bold text-teal-400">{s.value}</dt>
                  <dd className="mt-1 text-sm text-zinc-400">{s.label}</dd>
                </div>
              ))}
            </dl>
          </div>
        </section>

        {/* Features */}
        <section className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8 py-24">
          <div className="text-center mb-16">
            <h2 className="text-3xl font-bold text-white">Everything you need</h2>
            <p className="mt-3 text-zinc-400">Four endpoints, infinite possibilities.</p>
          </div>

          <div className="space-y-24">
            {features.map((f, i) => (
              <div
                key={f.id}
                id={f.id}
                className={`flex flex-col ${
                  i % 2 === 1 ? "md:flex-row-reverse" : "md:flex-row"
                } gap-12 items-center`}
              >
                <div className="flex-1 space-y-4">
                  <div className="inline-flex items-center gap-2 rounded-full border border-zinc-800 bg-zinc-900 px-3 py-1 text-sm">
                    <span>{f.icon}</span>
                    <span className="text-zinc-300 font-medium">{f.title}</span>
                  </div>
                  <h3 className="text-2xl font-bold text-white">{f.title}</h3>
                  <p className="text-zinc-400 leading-relaxed">{f.description}</p>
                  <Link
                    href={`/docs#${f.id}`}
                    className="inline-flex items-center gap-1 text-sm text-teal-500 hover:text-teal-400 transition-colors"
                  >
                    View API reference →
                  </Link>
                </div>
                <div className="flex-1 w-full">
                  <TabCodeBlock tabs={f.tabs} />
                </div>
              </div>
            ))}
          </div>
        </section>

        {/* CTA */}
        <section className="border-t border-zinc-800 bg-zinc-900/40">
          <div className="mx-auto max-w-3xl px-4 sm:px-6 lg:px-8 py-20 text-center">
            <h2 className="text-3xl font-bold text-white mb-4">Ready to start scraping?</h2>
            <p className="text-zinc-400 mb-8">Self-host in minutes with Docker or run locally.</p>
            <div className="rounded-lg border border-zinc-800 bg-zinc-950 p-4 text-left mb-8 font-mono text-sm">
              <p className="text-zinc-500"># Get started</p>
              <p className="text-zinc-300">git clone https://github.com/arvinddev14/SiloCrawl</p>
              <p className="text-zinc-300">cd silocrawl && cp .env.example .env</p>
              <p className="text-teal-400">docker compose up</p>
            </div>
            <Link
              href="/playground"
              className="inline-flex rounded-md bg-teal-500 px-8 py-3 text-sm font-semibold text-white hover:bg-teal-600 transition-colors"
            >
              Open playground
            </Link>
          </div>
        </section>
      </main>
      <Footer />
    </>
  );
}
