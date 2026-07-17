# SiloLoop

## Continuous Intelligence Engine for SiloCrawl

> **Mission:** Transform SiloCrawl from a deterministic web scraping
> toolkit into a self-improving autonomous web intelligence platform
> while preserving all existing APIs and features.

------------------------------------------------------------------------

# Design Principles

1.  **Never break existing APIs**
2.  **Keep SiloCrawl as the execution engine**
3.  **Add SiloLoop as an orchestration layer**
4.  **Every capability is observable**
5.  **Every output is verifiable**
6.  **Every failure is repairable**
7.  **Every execution contributes to future improvements**

------------------------------------------------------------------------

# High-Level Architecture

``` text
                  Client
                     │
                     ▼
                FastAPI Routes
                     │
        ┌────────────┴────────────┐
        │                         │
        ▼                         ▼
   Existing SiloCrawl        SiloLoop
  (Execution Engine)   (Intelligence Engine)
        │                         │
        └────────────┬────────────┘
                     ▼
              Final Response
```

------------------------------------------------------------------------

# Existing Components (Remain Unchanged)

-   `/v1/scrape`
-   `/v1/crawl`
-   `/v1/map`
-   `/v1/extract`
-   Python SDK
-   Frontend
-   Worker Queue
-   Redis
-   Playwright
-   Markdown Cleaner

These remain backwards compatible.

------------------------------------------------------------------------

# Proposed Folder Structure

``` text
app/
  api/
  services/
      fetcher.py
      crawler.py
      cleaner.py
      extractor.py
      mapper.py

      pdf.py
      verifier.py
      evaluator.py
      repair.py
      planner.py
      knowledge.py

  loop/
      orchestrator.py
      state_machine.py
      retries.py
      confidence.py
      telemetry.py
      benchmark.py
      memory.py
      strategy.py
```

------------------------------------------------------------------------

# SiloLoop Modules

## 1. Planner

Chooses the execution pipeline.

Responsibilities: - Detect input type - Select scraping strategy -
Select model - Estimate cost - Build execution graph

------------------------------------------------------------------------

## 2. Crawl Intelligence Loop

Pipeline

URL

↓

Fetch

↓

Failure?

↓

Retry Strategy

↓

Browser

↓

Headers

↓

Proxy

↓

Human Delay

↓

Success

Learns the best strategy per domain.

------------------------------------------------------------------------

## 3. Extraction Loop

Pipeline

Extract

↓

Schema Validation

↓

Missing Fields?

↓

Retry Missing Only

↓

Merge Results

↓

Confidence Score

↓

Return

------------------------------------------------------------------------

## 4. Verification Loop

Checks

-   Evidence exists
-   Hallucination detection
-   Cross-model verification
-   JSON validity
-   Schema validity

Produces a confidence score.

------------------------------------------------------------------------

## 5. Repair Loop

Repairs

-   Invalid JSON
-   Missing fields
-   Formatting
-   Type mismatch
-   Partial outputs

Without rerunning the full pipeline.

------------------------------------------------------------------------

## 6. Knowledge Loop

Stores

-   Domains
-   Entities
-   Relationships
-   Crawl history
-   Successful prompts
-   Successful strategies

Future crawls become smarter.

------------------------------------------------------------------------

## 7. PDF Intelligence

Support

-   PDF
-   DOCX
-   PPTX
-   XLSX
-   CSV
-   Images
-   OCR
-   Scanned PDFs

Pipeline

Document

↓

Parser

↓

OCR

↓

Tables

↓

Images

↓

Layout

↓

Chunks

↓

LLM

↓

Verification

↓

Knowledge Graph

------------------------------------------------------------------------

## 8. Frontend Improvement Loop

Collect

-   User actions
-   Wait times
-   Failures
-   Abandoned jobs

Generate UX recommendations.

------------------------------------------------------------------------

## 9. Code Improvement Loop

Every PR executes

-   Unit Tests
-   Integration Tests
-   Performance
-   Security
-   LLM Review
-   Refactoring Suggestions
-   Regression Tests

------------------------------------------------------------------------

## 10. Benchmark Loop

Continuously evaluate

-   Crawl Success
-   Extraction Accuracy
-   Latency
-   Token Usage
-   Hallucination Rate
-   Repair Rate

------------------------------------------------------------------------

# Dashboard Metrics

-   Crawl Success %
-   Extraction Confidence
-   Repair Success
-   Retry Count
-   Average Crawl Time
-   Prompt Versions
-   Domain Strategies Learned
-   Knowledge Graph Size
-   Benchmark Trends

------------------------------------------------------------------------

# Multi-Agent Architecture

Planner

↓

Crawler

↓

Extractor

↓

Verifier

↓

Repair

↓

Evaluator

↓

Knowledge

↓

Response

Suggested Models

  Agent           Model
  --------------- ----------------
  Planner         Qwen3
  Extractor       GPT-OSS 120B
  Verifier        Llama 3.3
  OCR             Qwen2.5-VL
  Code Review     DeepSeek Coder
  Summarization   GPT-OSS 120B

------------------------------------------------------------------------

# API Evolution

Existing endpoints remain unchanged.

Optional enhancements

-   POST /v1/pdf
-   POST /v1/document
-   POST /v1/vision
-   POST /v1/research

Optional query parameters

-   verify=true
-   repair=true
-   loop=true
-   benchmark=true

------------------------------------------------------------------------

# Long-Term Vision

## SiloCrawl

Reliable execution engine.

## SiloLoop

Adaptive intelligence layer.

Together they create an autonomous, open-source web intelligence
platform capable of continuous learning, verification, benchmarking,
repair, and optimization without breaking backward compatibility.

------------------------------------------------------------------------

# Suggested Roadmap

## Phase 1

-   Orchestrator
-   Confidence Scoring
-   Retry Engine
-   Verification Layer

## Phase 2

-   PDF Pipeline
-   Knowledge Graph
-   Prompt Versioning
-   Domain Strategy Memory

## Phase 3

-   Multi-Agent Coordination
-   Frontend Intelligence
-   Benchmark Suite
-   AI Code Review

## Phase 4

-   Autonomous Optimization
-   Continuous Learning
-   Cross-Model Evaluation
-   Self-improving Pipelines
