# DocVerify — Intelligent Document Inconsistency Detection

> A research-grade pipeline that detects inconsistencies across long documents while minimizing LLM context and cost.

## Overview

DocVerify is a **document intelligence system** designed for risk and compliance workflows. Instead of sending entire documents to an LLM, it uses a layered architecture — lexical pruning, semantic retrieval, targeted comparison, and context compression — to detect contradictions with minimal token usage.

**The core problem:** Enterprises maintain long, versioned documents (contracts, reports, procedures) where undetected inconsistencies can lead to compliance failures, financial losses, or legal disputes. Manual review is slow, expensive, and error-prone. Naive LLM approaches are costly at scale.

**The solution:** A multi-stage pipeline that finds the right evidence, compares it intelligently, and sends only the minimal context needed to the model for a decision.

## Demo

https://github.com/user-attachments/assets/docs-regex/DocVerify_Pipeline.mp4

> **[Download the full demo video](docs-regex/DocVerify_Pipeline.mp4)** if the player above doesn't render.

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│                    DocVerify Pipeline                    │
├─────────────────────────────────────────────────────────┤
│                                                          │
│  Raw Documents (PDF, scans, contracts)                   │
│        ↓                                                 │
│  ┌──────────────────┐                                   │
│  │  Ingestion       │  OCR + structured parsing          │
│  │  & Parsing       │  Pages, sections, tables, entities │
│  └────────┬─────────┘                                   │
│           ↓                                              │
│  ┌──────────────────┐                                   │
│  │  Lexical Search  │  Trigram index + inverted index    │
│  │  (Cursor-like)   │  Reduces candidate space to ~5%    │
│  └────────┬─────────┘                                   │
│           ↓                                              │
│  ┌──────────────────┐                                   │
│  │  Semantic Search │  Multi-vector retrieval (NextPlaid) │
│  │  (ColGREP)       │  Catches reformulations & nuance    │
│  └────────┬─────────┘                                   │
│           ↓                                              │
│  ┌──────────────────┐                                   │
│  │  Detection       │  Deterministic + LLM-assisted       │
│  │  & Comparison    │  Date conflicts, amount mismatches   │
│  └────────┬─────────┘                                   │
│           ↓                                              │
│  ┌──────────────────┐                                   │
│  │  Context         │  Minimal evidence bundles only       │
│  │  Compression     │  90%+ token reduction                │
│  └────────┬─────────┘                                   │
│           ↓                                              │
│  Structured report with evidence, severity & explanation  │
│                                                          │
└─────────────────────────────────────────────────────────┘
```

## Tech Stack

| Layer | Technology |
|-------|-----------|
| **Backend** | Python 3.12, FastAPI, Celery, Redis |
| **Search** | Cursor-like trigram index, NextPlaid multi-vector, ColGREP |
| **LLM** | LiteLLM + OpenRouter (model-agnostic) |
| **OCR** | Z.ai Layout Parsing API |
| **Storage** | MinIO S3, SQLite, local filesystem fallback |
| **Frontend** | Vue 3, Vite, Pinia |
| **Monitoring** | OpenTelemetry, Langfuse |
| **Infra** | Docker Compose |

## Research Methodology

This project is part of a doctoral thesis comparing search strategies for document inconsistency detection:

| Strategy | Description |
|----------|-------------|
| **Baseline** | Simple keyword matching |
| **Lexical (Cursor-like)** | Trigram + inverted index pruning |
| **Semantic** | Multi-vector retrieval via NextPlaid |
| **Hybrid** | Lexical pruning → Semantic re-ranking |
| **Regex (RG)** | Pattern-based structured field extraction |

Each strategy is evaluated on:
- **Retrieval quality** — Recall@k, MRR, nDCG
- **Detection accuracy** — Precision, Recall, F1
- **Economic efficiency** — Token count, cost per analysis, latency
- **Explanation quality** — Evidence span accuracy, conflict type correctness

### Evaluation Datasets

- **FIND** — Inconsistency detection with annotated evidence spans
- **Wikipedia Contradict** — Real semantic contradictions
- **LongBench** — Long context compression benchmark
- **CUAD** — Contract understanding and clause analysis

## Project Structure

```
projet-1/
├── backend-regex/          # FastAPI backend + Celery workers
│   ├── app/
│   │   ├── api/            # REST endpoints
│   │   ├── ingest/         # OCR, parsing, normalization
│   │   ├── search/         # Lexical, semantic, hybrid strategies
│   │   ├── detect/         # Inconsistency detection pipeline
│   │   ├── eval/           # Experiment runner & metrics
│   │   ├── llm/            # LiteLLM client & prompt templates
│   │   └── monitor/        # OpenTelemetry + Langfuse tracing
│   ├── workers/            # Celery async tasks
│   └── tests/              # Unit & integration tests
├── frontend-regex/         # Vue 3 dashboard
│   └── src/views/          # Documents, Search, Experiments, LLM
├── core-regx/              # Docker Compose (NextPlaid, Redis, MinIO)
└── docs-regex/             # Architecture docs & strategy papers
```

## Key Features

- **Multi-strategy search** — Compare lexical, semantic, hybrid, and regex approaches side-by-side
- **Experiment framework** — Run controlled experiments with configurable strategies, datasets, and metrics
- **Context compression** — Prove inconsistencies with 90%+ fewer tokens than naive approaches
- **Observability** — Full trace-level monitoring via Langfuse + OpenTelemetry
- **Async processing** — Celery workers for OCR, indexing, and long-running analyses
- **Model-agnostic** — Switch LLM providers via OpenRouter without code changes

## Getting Started

### Prerequisites

- Python 3.12+ with [uv](https://docs.astral.sh/uv/)
- Node.js 18+
- Docker & Docker Compose

### Backend

```bash
cd backend-regex
cp .env.example .env   # Configure API keys
uv sync
uv run uvicorn app.api.main:app --reload
```

### Workers

```bash
uv run celery -A workers.celery_app worker --loglevel=info
```

### Frontend

```bash
cd frontend-regex
npm install
npm run dev
```

### Infrastructure

```bash
cd core-regx
docker compose up -d   # Redis, MinIO, NextPlaid
```

## API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/v1/documents/upload` | Upload & OCR documents |
| `GET` | `/api/v1/documents` | List indexed documents |
| `POST` | `/api/v1/search` | Search with configurable strategy |
| `POST` | `/api/v1/detect` | Run inconsistency detection |
| `POST` | `/api/v1/experiments/run` | Launch experiment batch |
| `GET` | `/api/v1/experiments` | List experiment runs & results |
| `GET` | `/api/v1/llm/models` | Available LLM models |

## Research Hypotheses

1. **H1** — Lexical pruning reduces candidate space significantly with minimal recall loss for high-textual-signature cases
2. **H2** — Multi-vector semantic retrieval improves recall on reformulated contradictions vs. lexical-only
3. **H3** — Hybrid (lexical + semantic) outperforms either approach alone on the quality-cost tradeoff
4. **H4** — Minimal context bundles preserve detection quality while reducing token usage by 90%+

## License

Research project — doctoral thesis.
