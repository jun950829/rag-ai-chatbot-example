# Exmatch RAG App Template

Starter template for retrieval-augmented generation apps built by the team.

This repository is meant to give coworkers both:

- a practical starting point for new RAG projects
- a clear path for how those projects should be structured and evolved

The near-term target projects are exhibition assistants with very similar shape:

- ingest structured company/product/FAQ data
- build retrieval indexes
- expose a FastAPI backend
- answer user questions with grounded, domain-limited responses

## Why This Exists

The company wants to move toward higher-difficulty projects where AI workflows, retrieval, and domain-specific assistants matter.

Right now, the reference implementation knowledge mostly lives in one place.
This template exists to spread that knowledge into code, structure, and documentation.

## What This Template Should Eventually Support

- FastAPI service for chat, retrieval, ingestion, and admin workflows
- Postgres + pgvector for relational data and vector search
- Redis for caching, background jobs, and queueing when needed
- Docker-based local development
- configurable embedding provider and LLM provider
- batch refresh by default, with room for event-driven refresh later
- a predictable project structure teammates can reuse across clients

## Reference Project Shape

The current reference backend follows this broad flow:

1. ingest exhibition source data into base tables
2. build profile and evidence embeddings for searchable entities
3. retrieve candidate entities from pgvector
4. rerank, filter, and format grounded context
5. generate answers through a domain-restricted chat layer
6. handle FAQ-like flows separately when catalog retrieval is not the right tool

This template should preserve that shape while staying generic enough for reuse.

## Initial Scope For This Repository

The first foundation we are putting in place is intentionally small:

- project documentation
- environment and configuration setup
- FastAPI application starter
- Docker and Docker Compose setup

Later phases can add:

- ingestion pipelines
- embedding/indexing jobs
- retrieval services
- chat streaming endpoints
- background refresh workers
- tests and CI

## Suggested Implementation Phases

These phases mirror how we plan to teach and build the system as a team.

1. foundation
   Set up the repo, environment, app skeleton, Docker, and team conventions.
2. ingestion
   Add loaders for raw source data and define normalized base models.
3. embeddings
   Build profile/evidence indexing jobs and store vectors in pgvector.
4. retrieval
   Add search planning, retrieval, reranking, and context assembly.
5. chat
   Add domain-constrained answer generation and streaming APIs.
6. refresh strategy
   Add scheduled refresh first, then optional event-driven refresh later.
7. validation
   Add end-to-end checks, retrieval evaluation, and operational docs.

## Suggested Branch Strategy

For visibility and rollback, keep major work grouped into branches that match delivery phases.

Suggested branch names:

- `feat/foundation`
- `feat/ingestion`
- `feat/embeddings`
- `feat/retrieval`
- `feat/chat-runtime`
- `feat/refresh-strategy`
- `feat/evaluation`

Within each branch, keep commits small and explicit.

## Commit Convention

Use conventional prefixes:

- `feat: ...` for new functionality
- `fix: ...` for bug fixes
- `chore: ...` for setup, tooling, and maintenance
- `refactor: ...` for structural changes without behavior change

Examples:

- `feat: add health and readiness endpoints`
- `chore: add docker compose for local development`
- `refactor: split retrieval pipeline into service modules`

## Planned Project Structure

This is the target direction for the template:

```text
main/app/
  api/
  core/
  domain/
  pipelines/
  services/
  schemas/
  main.py

scripts/
tests/
docker/
```

Not every directory needs to exist on day one, but the structure should grow toward this shape.

## Development Principles

- Keep the core pipeline explicit and easy to trace.
- Separate generic RAG building blocks from project-specific rules.
- Prefer batch refresh first unless real-time updates are clearly needed.
- Make every external dependency configurable through environment variables.
- Design so teammates can replace data sources, prompts, and providers without rewriting the whole app.

## Local Development

The local development setup added in this repo is intended to support:

- running the FastAPI service in Docker
- running Postgres with pgvector
- keeping environment variables in `.env`
- using `.env.example` as the onboarding reference

More detailed setup instructions will be expanded as the foundation is committed.

### Quick Start

1. copy `.env.example` to `.env`
2. start the stack
3. open the docs or hit the health endpoint

```bash
cp .env.example .env
docker compose up --build
```

Optional local install without Docker:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements-api.txt
uvicorn main.app.main:app --reload
```

Local embedding worker (GPU; separate from Docker API):

```bash
export PYTHONPATH="$(pwd)"
pip install -r requirements-api.txt -r embedding/requirements.txt
uvicorn embedding.main:app --reload --host 0.0.0.0 --port 8765
```

RAG pipeline and embedding UI live under `main/app/rag` and `/tools/embedding` on the API server. See `embedding/README.md` and `main/app/rag/README.md`.

Useful URLs:

- app: `http://localhost:8000`
- docs: `http://localhost:8000/docs`
- health: `http://localhost:8000/api/v1/health`
- embedding tool UI: `http://localhost:8000/tools/embedding`

## What Good Looks Like

When this template matures, a teammate should be able to:

1. clone the repo
2. copy `.env.example` to `.env`
3. start the stack with Docker Compose
4. confirm the app is healthy
5. add a project-specific ingestion source
6. plug in embeddings, retrieval, and chat logic without changing the foundation

## Status

This repository is in the foundation stage.

Current focus:

- README
- project setup
- FastAPI starter
- Docker starter
