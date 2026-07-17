import { Navbar } from "@/components/navbar";
import { Footer } from "@/components/footer";
import { CodeBlock } from "@/components/code-block";

interface Field {
  name: string;
  type: string;
  required?: boolean;
  description: string;
}

interface EndpointDoc {
  id: string;
  method: string;
  path: string;
  title: string;
  description: string;
  request: Field[];
  response: Field[];
  example: string;
}

const endpoints: EndpointDoc[] = [
  {
    id: "scrape",
    method: "POST",
    path: "/v1/scrape",
    title: "Scrape",
    description:
      "Fetch a single URL and return its content in one or more formats. Optionally render JavaScript before extracting content.",
    request: [
      { name: "url", type: "string", required: true, description: "The URL to scrape." },
      {
        name: "formats",
        type: "array<string>",
        description: 'Output formats. One or more of: "markdown", "html", "text", "links", "screenshot". Defaults to ["markdown"]. Requesting "screenshot" renders the page in a headless browser.',
      },
      {
        name: "render_js",
        type: "boolean",
        description: "Use Playwright to render JavaScript before extracting. Defaults to false.",
      },
    ],
    response: [
      { name: "markdown", type: "string | null", description: "Page content as Markdown." },
      { name: "html", type: "string | null", description: "Cleaned HTML content." },
      { name: "text", type: "string | null", description: "Plain text content." },
      { name: "links", type: "string[]", description: "All absolute URLs found on the page." },
      {
        name: "screenshot",
        type: "string | null",
        description: "Base64-encoded full-page PNG (when requested).",
      },
      {
        name: "metadata",
        type: "object",
        description: "title, description, source_url, status_code, language.",
      },
    ],
    example: `curl -X POST http://localhost:8000/v1/scrape \\
  -H "content-type: application/json" \\
  -d '{
    "url": "https://example.com",
    "formats": ["markdown", "links"]
  }'`,
  },
  {
    id: "map",
    method: "POST",
    path: "/v1/map",
    title: "Map",
    description:
      "Quickly discover all URLs on a domain. Combines sitemap.xml parsing with homepage link extraction for maximum coverage.",
    request: [
      { name: "url", type: "string", required: true, description: "The domain root URL to map." },
      {
        name: "limit",
        type: "integer",
        description: "Maximum number of URLs to return. Defaults to 5000 (max 50000).",
      },
      {
        name: "include_subdomains",
        type: "boolean",
        description: "Include URLs on subdomains of the target domain. Defaults to false.",
      },
      {
        name: "search",
        type: "string",
        description: "Only return URLs containing this substring (case-insensitive).",
      },
    ],
    response: [
      { name: "base_url", type: "string", description: "The normalised root URL that was mapped." },
      { name: "links", type: "string[]", description: "Sorted list of discovered URLs on the domain." },
      { name: "count", type: "integer", description: "Number of URLs returned." },
    ],
    example: `curl -X POST http://localhost:8000/v1/map \\
  -H "content-type: application/json" \\
  -d '{"url": "https://example.com", "limit": 100}'`,
  },
  {
    id: "extract",
    method: "POST",
    path: "/v1/extract",
    title: "Extract",
    description:
      "Use an LLM to extract structured data from a URL or raw content according to a JSON Schema you provide. The model is forced to return valid JSON matching your schema.",
    request: [
      {
        name: "url",
        type: "string",
        description: "URL to scrape and extract from. Either url or content is required.",
      },
      {
        name: "content",
        type: "string",
        description: "Raw text/markdown to extract from directly (skips scraping).",
      },
      {
        name: "json_schema",
        type: "object",
        required: true,
        description: "A JSON Schema object describing the structure to extract.",
      },
      {
        name: "prompt",
        type: "string",
        description: "Optional natural-language instruction for the LLM.",
      },
      { name: "render_js", type: "boolean", description: "Render JavaScript before scraping." },
    ],
    response: [
      {
        name: "data",
        type: "object",
        description: "Extracted data conforming to the provided json_schema.",
      },
      { name: "source_url", type: "string | null", description: "The URL that was scraped." },
    ],
    example: `curl -X POST http://localhost:8000/v1/extract \\
  -H "content-type: application/json" \\
  -d '{
    "url": "https://example.com",
    "json_schema": {
      "type": "object",
      "properties": {
        "title": {"type": "string"},
        "summary": {"type": "string"},
        "topics": {"type": "array", "items": {"type": "string"}}
      }
    },
    "prompt": "Extract the page title, a brief summary, and main topics."
  }'`,
  },
  {
    id: "crawl",
    method: "POST",
    path: "/v1/crawl",
    title: "Crawl",
    description:
      "Start an asynchronous crawl job that recursively follows links from a starting URL. Returns a job ID immediately. Poll the status endpoint to track progress and retrieve results.",
    request: [
      { name: "url", type: "string", required: true, description: "The starting URL for the crawl." },
      {
        name: "max_pages",
        type: "integer",
        description: "Maximum number of pages to crawl. Defaults to 100 (max 10000).",
      },
      { name: "max_depth", type: "integer", description: "Maximum link depth. Defaults to 3 (max 10)." },
      {
        name: "formats",
        type: "array<string>",
        description: 'Output formats for each page. Defaults to ["markdown"].',
      },
      { name: "render_js", type: "boolean", description: "Render JavaScript on every page. Defaults to false." },
      {
        name: "include_paths",
        type: "array<string>",
        description: "Regex patterns — only URLs matching at least one are followed.",
      },
      {
        name: "exclude_paths",
        type: "array<string>",
        description: "Regex patterns — URLs matching any are skipped.",
      },
      {
        name: "allow_external",
        type: "boolean",
        description: "Follow links to external domains. Defaults to false.",
      },
    ],
    response: [
      { name: "id", type: "string", description: "UUID for the crawl job. Use this to poll status." },
      { name: "status", type: "string", description: '"queued", "running", "completed", or "failed".' },
      { name: "total", type: "integer", description: "Total pages discovered (populated as the job runs)." },
      { name: "completed", type: "integer", description: "Number of pages scraped so far." },
      { name: "data", type: "ScrapeResult[]", description: "Scraped pages (populated when the job completes)." },
      {
        name: "failed_pages",
        type: "object[]",
        description: "Pages that failed, each as { url, error }.",
      },
      { name: "error", type: "string | null", description: "Job-level error message, if the job failed." },
    ],
    example: `# 1. Start the crawl
curl -X POST http://localhost:8000/v1/crawl \\
  -H "content-type: application/json" \\
  -d '{
    "url": "https://example.com",
    "max_pages": 20,
    "max_depth": 2
  }'

# 2. Poll status
curl http://localhost:8000/v1/crawl/<job_id>`,
  },
];

function MethodBadge({ method }: { method: string }) {
  return (
    <span className="rounded px-2 py-0.5 text-xs font-bold font-mono bg-teal-500/20 text-teal-400 border border-teal-500/30">
      {method}
    </span>
  );
}

function FieldTable({ fields }: { fields: Field[] }) {
  return (
    <div className="overflow-x-auto rounded-lg border border-zinc-800">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-zinc-800 bg-zinc-900/60">
            <th className="text-left px-4 py-2.5 text-xs font-medium text-zinc-400">Field</th>
            <th className="text-left px-4 py-2.5 text-xs font-medium text-zinc-400">Type</th>
            <th className="text-left px-4 py-2.5 text-xs font-medium text-zinc-400">Description</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-zinc-800/60">
          {fields.map((f) => (
            <tr key={f.name} className="bg-zinc-900/20">
              <td className="px-4 py-2.5 font-mono text-xs">
                <span className="text-zinc-200">{f.name}</span>
                {f.required && <span className="ml-1.5 text-red-400 text-xs">*</span>}
              </td>
              <td className="px-4 py-2.5 font-mono text-xs text-teal-400/80">{f.type}</td>
              <td className="px-4 py-2.5 text-xs text-zinc-400">{f.description}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export default function DocsPage() {
  return (
    <>
      <Navbar />
      <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8 py-10 flex gap-10">
        {/* Sidebar */}
        <aside className="hidden lg:block w-52 shrink-0">
          <div className="sticky top-24 space-y-1">
            <p className="text-xs font-semibold text-zinc-500 uppercase tracking-wider mb-3">
              Endpoints
            </p>
            {endpoints.map((e) => (
              <a
                key={e.id}
                href={`#${e.id}`}
                className="flex items-center gap-2 rounded px-2 py-1.5 text-sm text-zinc-400 hover:text-white hover:bg-zinc-800 transition-colors"
              >
                <span className="text-xs font-mono text-teal-500">{e.method}</span>
                {e.title}
              </a>
            ))}
            <div className="pt-4 border-t border-zinc-800 mt-4">
              <a
                href="#health"
                className="flex items-center gap-2 rounded px-2 py-1.5 text-sm text-zinc-400 hover:text-white hover:bg-zinc-800 transition-colors"
              >
                <span className="text-xs font-mono text-zinc-500">GET</span>
                Health
              </a>
            </div>
          </div>
        </aside>

        {/* Main */}
        <main className="flex-1 min-w-0 space-y-16">
          <div>
            <h1 className="text-3xl font-bold text-white mb-2">API Reference</h1>
            <p className="text-zinc-400">
              All endpoints are available at{" "}
              <code className="rounded bg-zinc-800 px-1.5 py-0.5 text-teal-400 text-sm font-mono">
                http://localhost:8000
              </code>{" "}
              by default.
            </p>
          </div>

          {endpoints.map((e) => (
            <section key={e.id} id={e.id} className="scroll-mt-20">
              <div className="flex items-center gap-3 mb-3">
                <MethodBadge method={e.method} />
                <code className="text-zinc-200 font-mono text-sm">{e.path}</code>
              </div>
              <h2 className="text-xl font-bold text-white mb-2">{e.title}</h2>
              <p className="text-zinc-400 text-sm mb-6 leading-relaxed">{e.description}</p>

              <h3 className="text-sm font-semibold text-zinc-300 mb-2">Request body</h3>
              <FieldTable fields={e.request} />

              <h3 className="text-sm font-semibold text-zinc-300 mt-6 mb-2">Response</h3>
              <FieldTable fields={e.response} />

              <h3 className="text-sm font-semibold text-zinc-300 mt-6 mb-2">Example</h3>
              <CodeBlock code={e.example} language="bash" />
            </section>
          ))}

          {/* Health */}
          <section id="health" className="scroll-mt-20">
            <div className="flex items-center gap-3 mb-3">
              <span className="rounded px-2 py-0.5 text-xs font-bold font-mono bg-zinc-700/40 text-zinc-400 border border-zinc-700">
                GET
              </span>
              <code className="text-zinc-200 font-mono text-sm">/health</code>
            </div>
            <h2 className="text-xl font-bold text-white mb-2">Health Check</h2>
            <p className="text-zinc-400 text-sm mb-6">Returns a 200 OK when the API is running.</p>
            <CodeBlock code={`curl http://localhost:8000/health\n# {"status": "ok"}`} language="bash" />
          </section>
        </main>
      </div>
      <Footer />
    </>
  );
}
