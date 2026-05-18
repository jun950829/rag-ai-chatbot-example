---
name: Exmatch project context
description: Overview of the frontend+backend template pair, V1 scope, API contract, and build priorities
type: project
---

This repo (`exmatch-template-frontend`) is the React/TS frontend pair to the FastAPI backend at `/Users/minte/Desktop/exmatch-template`.

**Why:** Build a reusable chat UI for expo assistants (catalog search, FAQ visitor/exhibitor flows) that cleanly consumes the backend's stable API contract.

## Backend summary
- FastAPI + Postgres/pgvector + Redis, runs via Docker Compose
- Local base URL: `http://localhost/api/v1` (nginx is the public entrypoint)
- Wrapped JSON responses: `{ status, message, data }` for success; bare `{ detail }` for errors
- Three session modes: `catalog`, `faq_visitor`, `faq_exhibitor`
- Thread ownership is a soft data contract (`owner_type` / `owner_id`), not auth

## Key endpoints
- `POST /api/v1/chat/threads` — create thread, returns initial greeting
- `GET  /api/v1/chat/threads?event_slug=&owner_type=&owner_id=` — owner thread list
- `GET  /api/v1/chat/threads/{thread_id}/messages` — load full thread
- `POST /api/v1/chat/threads/{thread_id}/messages/stream` — POST-based SSE streaming
- `GET  /api/v1/health` / `/api/v1/ready`
- CRUD for `/api/v1/companies` and `/api/v1/products` (useful for QA/debug, not required for chat UI)

## Streaming (critical)
- `EventSource` does NOT work — streaming is POST-based
- Use `fetch()` + `ReadableStream`, parse SSE manually
- Event sequence: `stage` → `stage` → `stage` → N×`delta` → `final` → `done`
- Append `delta.text` progressively; replace with `final` payload on completion

## Frontend V1 scope
- thread bootstrap → chat message list → POST SSE streaming → catalog cards → FAQ mode switching → thread list for known owner → basic loading/error/retry → desktop + mobile responsive

## Out of scope for V1
- auth, analytics, admin CRUD, reporting, multi-event management, catalog ingestion UI

## Suggested stack
- React + TypeScript + Vite
- Small local state + feature-level hooks (no heavy framework needed)

## Suggested build order (order matters)
1. Project setup + app shell + API client layer + health check
2. Thread bootstrap + message list + streaming parser + basic chat UI
3. Catalog cards + FAQ mode entry + thread restore
4. Owner-scoped thread list + polish + mobile + error UX

## Integration risks to watch
- Assuming `EventSource` works for streaming (it doesn't — POST required)
- Treating wrapped success payloads as raw JSON (must unwrap `.data`)
- Rebuilding server `ConversationState` on the client (backend owns state)
- Ignoring `session_mode`
- Treating `owner_type`/`owner_id` as secure auth (it is not)

**How to apply:** Use these constraints when designing or reviewing any API layer, streaming, or state management code.
