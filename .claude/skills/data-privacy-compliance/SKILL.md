---
name: data-privacy-compliance
description: >-
  Use when working on anything that touches personal data in SiloCrawl —
  telemetry, logging, scraped content, crawl storage, retention, data-subject
  requests (access/deletion/export), consent, or the privacy policy. Applies
  GDPR / CCPA-CPRA / HIPAA principles to SiloCrawl's actual data flows.
---

# Data Privacy Compliance (SiloCrawl)

Guidance for keeping SiloCrawl's data handling compliant. SiloCrawl is a
self-hosted scraping toolkit, so **the operator is the data controller** — this
skill helps them (and us, when we build features) apply privacy-by-design.

> Adapted for SiloCrawl from the community "data-privacy-compliance" skill
> (davila7/claude-code-templates). Frameworks and thresholds below are
> summarized for engineering use, not legal advice.

## When to apply

Reach for this skill whenever a change:
- adds or alters **data collection** (new telemetry event, new logged field,
  storing scraped/crawled content, request bodies);
- changes **retention** (how long anything is kept, TTLs, deletion jobs);
- exposes data **outbound** (a new endpoint returning stored data, an external
  call that ships user content — e.g. the LLM endpoint, the CI code-review);
- touches the **privacy policy** or any data-subject-rights flow.

## Regulatory frameworks (thresholds to remember)

| Framework | Scope | Max penalty |
|-----------|-------|-------------|
| **GDPR** | EU residents' data, wherever processed | €20M or 4% of global annual revenue |
| **CCPA/CPRA** | California residents | $7,500 per intentional violation |
| **HIPAA** | US Protected Health Information (PHI) | $1.5M per violation category / year |

SiloCrawl ships no health features; HIPAA only matters if an operator crawls PHI.

## Data-subject rights (must be satisfiable)

1. **Access** — export a subject's stored data in a structured form (1–3 month
   response window under GDPR).
2. **Deletion** — remove on request, minus data under a legal retention duty.
3. **Portability** — export in a machine-readable format (JSON/CSV/XML).
4. **Object / restrict** — stop processing for marketing, profiling, or
   "legitimate interest" on request.

Engineering implication: any table that stores personal data needs a
**delete-by-subject** and **export-by-subject** path. Prefer keying such data so
those operations are possible (e.g. by domain/source/job id). Erasures are
recorded in `deletion_log` (`GET /v1/audit/deletions`) — **metadata only, never
the deleted content**, so the audit trail survives a deletion without
re-introducing the data.

## Consent (when applicable)

Valid consent is: freely given · specific per purpose · informed · unambiguous
affirmative action · easily withdrawable. Frontend UX telemetry (`/v1/events`)
should be **opt-in or clearly disclosed**, never silently identifying.

## Privacy-by-design (apply to every feature)

- **Data minimization** — collect only what a feature needs. Don't log full
  request bodies or response content "just in case."
- **Purpose limitation** — use data only for the stated purpose.
- **Storage limitation** — set a retention period and enforce it (TTL /
  scheduled deletion). Unbounded growth is a compliance risk, not just a disk
  one.

## SiloCrawl's data map (keep current)

| Data | Where | Personal? | Retention |
|------|-------|-----------|-----------|
| Telemetry events (endpoint, duration, UX signals) | SQLite `telemetry_events` | Low (no PII by design) | Operator-defined |
| Crawl/scrape results (page content) | SQLite `crawl_jobs` (in-process runner) | Possibly (if pages contain personal data) | Operator-defined; no TTL |
| Access logs (method, path, status, api_key_id hash) | stdout / operator's log sink | IP/UA only if operator adds them | Operator-defined |
| API keys | env / config, compared timing-safe, stored hashed in logs | Yes (secret) | Lifetime of the key |
| Content sent to the LLM endpoint | HuggingFace inference endpoint (external) | Possibly | Governed by that provider |
| Deletion audit trail | SQLite `deletion_log` | No — metadata only, no content | Retained (compliance evidence) |

Rules that follow from the map:
- **Do not add PII to telemetry or logs** without a documented reason and
  retention. `api_key_id` is a truncated sha256, never the raw key — keep it so.
- Scraped content **may contain third parties' personal data**; treat the
  `crawl_jobs` store as personal data and provide delete-by-job.
- The LLM and CI-review paths send content to an external service — disclose
  this in the privacy policy and keep it operator-configurable.

## Breach response

GDPR requires notifying the supervisory authority within **72 hours** of
becoming aware of a breach, and affected individuals when risk is high. Keep
enough audit trail (who/what/when) to support that, without over-collecting.

## Privacy policy — required elements

A compliant policy discloses: controller identity, data categories collected,
legal basis, retention periods, third-party sharing (LLM endpoint, any
analytics), international transfers, and how to exercise subject rights. The
frontend `/privacy` page is the canonical policy; keep it in sync with the data
map above whenever data handling changes.

## Compliance checklist (per data-touching change)

- [ ] Is the new data actually necessary? (minimization)
- [ ] Is it personal data? If so: retention set + delete/export path exists?
- [ ] If deletable, is the erasure logged to `deletion_log` (metadata only)?
- [ ] Does it leave the box (external call)? Disclosed in the privacy policy?
- [ ] Logs/telemetry free of raw PII and secrets?
- [ ] Privacy policy still accurate? Update `/privacy` if not.
