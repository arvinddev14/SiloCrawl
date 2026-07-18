import { Navbar } from "@/components/navbar";
import { Footer } from "@/components/footer";

export const metadata = {
  title: "Privacy Policy · SiloCrawl",
  description:
    "How SiloCrawl handles personal data, and the data-subject rights it supports (GDPR / CCPA-CPRA aligned).",
};

const LAST_UPDATED = "17 July 2026";

interface Section {
  id: string;
  heading: string;
  body: React.ReactNode;
}

const dataRows: { data: string; where: string; personal: string; retention: string }[] = [
  {
    data: "Telemetry (endpoint name, duration, status, UX signals)",
    where: "Local SQLite",
    personal: "No PII by design",
    retention: "Operator-defined",
  },
  {
    data: "Crawl & scrape results (page content)",
    where: "Local SQLite",
    personal: "Possibly — pages may contain personal data",
    retention: "Until deleted; no TTL",
  },
  {
    data: "Access logs (method, path, status, hashed key id)",
    where: "Operator's log sink",
    personal: "Only if the operator adds IP/UA",
    retention: "Operator-defined",
  },
  {
    data: "API keys (when auth is enabled)",
    where: "Operator config; hashed in logs",
    personal: "Secret credential",
    retention: "Lifetime of the key",
  },
  {
    data: "Content sent for LLM extraction",
    where: "External inference endpoint",
    personal: "Possibly",
    retention: "Governed by that provider",
  },
];

const sections: Section[] = [
  {
    id: "who",
    heading: "1. Who controls your data",
    body: (
      <>
        <p>
          SiloCrawl is open-source software that you run yourself. When you self-host it,{" "}
          <strong className="text-zinc-200">you are the data controller</strong> for everything
          it processes, and this policy describes how the software handles data so you can meet
          your obligations. The SiloCrawl project authors do not receive, store, or have access
          to any data processed by your instance.
        </p>
      </>
    ),
  },
  {
    id: "collect",
    heading: "2. What data is processed",
    body: (
      <>
        <p>
          SiloCrawl collects only what its features need. Everything below stays on the
          infrastructure you run it on, except where noted as an external call.
        </p>
        <div className="mt-4 overflow-x-auto rounded-lg border border-zinc-800">
          <table className="w-full text-sm">
            <thead className="bg-zinc-900/60 text-left text-zinc-300">
              <tr>
                <th className="px-4 py-2 font-medium">Data</th>
                <th className="px-4 py-2 font-medium">Where it lives</th>
                <th className="px-4 py-2 font-medium">Personal data?</th>
                <th className="px-4 py-2 font-medium">Retention</th>
              </tr>
            </thead>
            <tbody className="text-zinc-400">
              {dataRows.map((r) => (
                <tr key={r.data} className="border-t border-zinc-800 align-top">
                  <td className="px-4 py-2">{r.data}</td>
                  <td className="px-4 py-2">{r.where}</td>
                  <td className="px-4 py-2">{r.personal}</td>
                  <td className="px-4 py-2">{r.retention}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </>
    ),
  },
  {
    id: "use",
    heading: "3. How data is used (purpose limitation)",
    body: (
      <p>
        Data is used solely to operate the service you invoked: fulfilling a scrape, crawl, map,
        or extract request; running the optional self-improvement loops (verification, repair,
        benchmarking); and showing operational metrics on the dashboard. SiloCrawl does not sell
        data, does not serve advertising, and does not profile end users.
      </p>
    ),
  },
  {
    id: "sharing",
    heading: "4. When data leaves your instance",
    body: (
      <>
        <p>Two features make outbound calls, both operator-configurable:</p>
        <ul className="mt-3 list-disc space-y-2 pl-5">
          <li>
            <strong className="text-zinc-200">LLM extraction.</strong> When you use{" "}
            <code className="text-teal-400">/v1/extract</code> (or the loop pipelines), the page
            content or text you supply is sent to the inference endpoint you configure
            (by default an open-source model on a HuggingFace endpoint). That provider&apos;s
            terms govern what it does with the content.
          </li>
          <li>
            <strong className="text-zinc-200">CI code review (optional).</strong> If you enable
            the LLM code-review workflow, code diffs are sent to the same inference endpoint. It
            is skipped entirely when no credentials are set.
          </li>
        </ul>
        <p className="mt-3">
          No other third parties receive data. The frontend talks only to your own SiloCrawl API.
        </p>
      </>
    ),
  },
  {
    id: "rights",
    heading: "5. Your rights",
    body: (
      <>
        <p>
          Because SiloCrawl stores its state in a local SQLite database that the operator
          controls, an operator can satisfy data-subject requests directly through the API:
        </p>
        <ul className="mt-3 list-disc space-y-2 pl-5">
          <li>
            <strong className="text-zinc-200">Access &amp; portability</strong> — list stored
            crawl jobs with <code className="text-teal-400">GET /v1/crawl</code>, export a job and
            the content it captured with{" "}
            <code className="text-teal-400">GET /v1/crawl/{"{id}"}</code>, and export raw
            telemetry with <code className="text-teal-400">GET /v1/telemetry</code> — all as JSON.
          </li>
          <li>
            <strong className="text-zinc-200">Deletion</strong> — erase a crawl job and its
            captured content with <code className="text-teal-400">DELETE /v1/crawl/{"{id}"}</code>;
            purge telemetry by time window with{" "}
            <code className="text-teal-400">DELETE /v1/telemetry</code>.
          </li>
          <li>
            <strong className="text-zinc-200">Objection / restriction</strong> — telemetry can be
            disabled entirely with <code className="text-teal-400">TELEMETRY_ENABLED=false</code>.
          </li>
        </ul>
        <p className="mt-3">
          Every erasure is recorded in an append-only deletion log (
          <code className="text-teal-400">GET /v1/audit/deletions</code>) so an operator can
          demonstrate compliance. That log stores <strong className="text-zinc-200">metadata only</strong>{" "}
          — what was deleted, how many records, by whom, and when — never the deleted content
          itself, so it can be retained after an erasure without re-introducing your data.
        </p>
        <p className="mt-3">
          If you are an end user whose data may have been collected by an organization running
          SiloCrawl, direct your request to that organization — they are the controller.
        </p>
      </>
    ),
  },
  {
    id: "retention",
    heading: "6. Retention",
    body: (
      <p>
        SiloCrawl does not impose a fixed retention period — jobs and telemetry persist in SQLite
        until deleted. Operators are responsible for setting a retention schedule appropriate to
        their legal basis and enforcing it. Storing personal data indefinitely without a purpose
        is itself a compliance risk under GDPR&apos;s storage-limitation principle.
      </p>
    ),
  },
  {
    id: "security",
    heading: "7. How data is protected",
    body: (
      <ul className="list-disc space-y-2 pl-5">
        <li>Outbound fetches are guarded against SSRF — requests to private, loopback, and cloud-metadata addresses are refused, and connections are pinned to the validated IP.</li>
        <li>Optional API-key authentication uses constant-time comparison; only a truncated hash of a key ever appears in logs, never the raw key.</li>
        <li>Response bodies and uploads are size-capped to bound memory exposure.</li>
        <li>Dependencies are monitored for known vulnerabilities.</li>
      </ul>
    ),
  },
  {
    id: "children",
    heading: "8. Children",
    body: (
      <p>
        SiloCrawl is developer infrastructure and is not directed at children. It does not
        knowingly collect data from anyone under 16.
      </p>
    ),
  },
  {
    id: "changes",
    heading: "9. Changes to this policy",
    body: (
      <p>
        This policy is versioned with the SiloCrawl source. Material changes to how the software
        handles data will be reflected here and in the changelog. The date below marks the last
        revision.
      </p>
    ),
  },
  {
    id: "contact",
    heading: "10. Contact",
    body: (
      <p>
        Questions about the software&apos;s data handling can be raised via the{" "}
        <a
          href="https://github.com/arvinddev14/SiloCrawl"
          target="_blank"
          rel="noopener noreferrer"
          className="text-teal-400 hover:text-teal-300"
        >
          project repository
        </a>
        . For data held by a specific SiloCrawl deployment, contact that deployment&apos;s
        operator.
      </p>
    ),
  },
];

export default function PrivacyPage() {
  return (
    <>
      <Navbar />
      <main className="flex-1">
        <div className="mx-auto max-w-3xl px-4 sm:px-6 lg:px-8 py-16">
          <header className="border-b border-zinc-800 pb-8">
            <h1 className="text-4xl font-bold tracking-tight text-white">Privacy Policy</h1>
            <p className="mt-3 text-zinc-400">
              How SiloCrawl handles personal data. Aligned with GDPR and CCPA/CPRA principles.
            </p>
            <p className="mt-2 text-sm text-zinc-500">Last updated: {LAST_UPDATED}</p>
          </header>

          <div className="mt-10 space-y-12">
            {sections.map((s) => (
              <section key={s.id} id={s.id} className="scroll-mt-20">
                <h2 className="text-xl font-semibold text-white">{s.heading}</h2>
                <div className="mt-3 space-y-3 leading-relaxed text-zinc-400">{s.body}</div>
              </section>
            ))}
          </div>

          <p className="mt-14 rounded-lg border border-zinc-800 bg-zinc-900/40 p-4 text-sm text-zinc-500">
            This document explains how the SiloCrawl software processes data and is provided to
            help operators meet their obligations. It is not legal advice; operators should
            confirm their own compliance posture.
          </p>
        </div>
      </main>
      <Footer />
    </>
  );
}
