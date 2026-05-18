# Exmatch Frontend Template

Starter frontend repository for expo assistant projects built on top of the Exmatch backend template.

This repo is intentionally light right now. It is meant to become the reusable frontend pair to:

- `/Users/minte/Desktop/exmatch-template`

The backend template already supports:

- event-scoped catalog data
- event-scoped FAQ data
- persisted chat threads
- POST-based SSE message streaming
- owner-scoped thread listing

This frontend repo should be built to match that backend contract cleanly.

## Goal

Provide a reusable chat UI for expo assistants with:

- catalog search flows
- FAQ visitor flows
- FAQ exhibitor flows
- persisted conversation threads
- streaming answers
- owner-linked chat history when the parent app provides identity

This frontend should not try to reimplement backend logic. The backend is the source of truth for:

- conversation state
- routing
- thread persistence
- FAQ vs catalog mode behavior

The frontend should own:

- rendering
- input UX
- streaming display
- thread navigation
- app-level identity wiring

## Current Status

This repository is currently a clean starting point with documentation only.

That is intentional.

The backend contract is now stable enough that this frontend can be built from scratch with less ambiguity than the previous project.

## Recommended Frontend Scope

### V1

- thread bootstrap
- chat message list
- POST-based SSE streaming
- catalog cards
- FAQ mode switching
- thread list for a known owner
- basic loading / error / retry states
- desktop and mobile responsive layout

### Explicitly Out of Scope For V1

- auth system
- analytics dashboards
- admin CRUD UI
- reporting UI
- multi-event management UI
- direct catalog ingestion UI

## Backend Integration Reference

Use the backend handoff doc here:

- [frontend-api-handoff.md](https://gitlab.com/momenti-hq/exmatch/exmatch-template/-/blob/main/docs/frontend-api-handoff.md)

That document is the main contract for:

- endpoint paths
- request payloads
- wrapped response format
- SSE event shapes
- thread ownership behavior
- limitations and caveats

## Recommended Frontend Flow

The real UI path should be:

1. create a thread
2. render the initial assistant greeting
3. send user messages through the threaded streaming endpoint
4. render `delta` chunks while streaming
5. finalize message state from the `final` SSE event
6. reload thread history when restoring a conversation

Do not build the main UI around the stateless debug route.

## Backend Endpoints The Frontend Should Care About

### Health

- `GET /api/v1/health`

### Chat

- `POST /api/v1/chat/threads`
- `GET /api/v1/chat/threads?event_slug=...&owner_type=...&owner_id=...`
- `GET /api/v1/chat/threads/{thread_id}/messages`
- `POST /api/v1/chat/threads/{thread_id}/messages/stream`

### Optional Direct Reads

- `GET /api/v1/companies`
- `GET /api/v1/companies/{company_id}`
- `GET /api/v1/products`
- `GET /api/v1/products/{product_id}`

## Important Backend Behavior

### Wrapped JSON responses

Most non-streaming endpoints return:

```json
{
  "status": 200,
  "message": "Success",
  "data": {}
}
```

Frontend code should unwrap `data` before rendering.

### POST-based SSE

Streaming chat is done via `POST`, not `GET`.

That means:

- plain `EventSource` is not enough
- use `fetch()` with a readable stream
- parse SSE event blocks manually

Expected event sequence:

- `stage`
- `stage`
- `stage`
- zero or more `delta`
- `final`
- `done`

### Thread ownership

Threads may optionally be created with:

- `owner_type`
- `owner_id`

This is a soft identity hook for the parent app.

It is not access control.

### Session modes

Supported modes:

- `catalog`
- `faq_visitor`
- `faq_exhibitor`

The frontend should treat these as real separate entry states.

## Suggested Frontend Architecture

I would keep the frontend split into a few clean areas:

```text
src/
  app/
  api/
  features/
    chat/
    threads/
    faq/
    catalog/
  components/
  hooks/
  lib/
  styles/
```

### Suggested responsibility split

- `api/`
  - fetch wrappers
  - thread bootstrap calls
  - stream parser
  - direct company/product reads

- `features/chat/`
  - message composer
  - streaming state
  - message rendering

- `features/threads/`
  - owner thread list
  - thread restore

- `features/catalog/`
  - card rendering
  - detail CTA behavior

- `features/faq/`
  - mode-specific entry points
  - FAQ clarification UI if returned by backend

## Suggested State Model

At minimum, keep:

- `threadId`
- `sessionMode`
- `lang`
- `messages`
- `streamingText`
- `isStreaming`
- `ownerType`
- `ownerId`

Important rule:

- the backend owns conversation state
- the frontend owns view state

Do not attempt to recreate backend `ConversationState` on the frontend for threaded usage.

## UI Requirements

The UI should support:

- a clean chat timeline
- markdown-safe plain text rendering
- assistant cards under relevant messages
- graceful handling of empty results
- retry behavior for failed stream requests
- clear mode entry for:
  - product/company search
  - visitor FAQ
  - exhibitor FAQ

On mobile, the layout should prioritize:

- readable message width
- easy composer interaction
- scroll stability during streaming

## Suggested Build Priorities

### Phase 1

- project setup
- app shell
- API client layer
- health check wiring

### Phase 2

- thread bootstrap
- message list
- streaming parser
- basic chat UI

### Phase 3

- catalog cards
- FAQ mode entry
- thread restore

### Phase 4

- owner-scoped thread list
- polish
- mobile responsiveness
- error UX hardening

## Suggested Environment Variables

Expected frontend env shape:

```env
VITE_API_BASE_URL=http://localhost/api/v1
```

If you use Next.js instead of Vite:

```env
NEXT_PUBLIC_API_BASE_URL=http://localhost/api/v1
```

Keep the base URL configurable from day one.

## Recommended Stack

If building this today, I would keep it simple:

- React
- TypeScript
- Vite
- small local state plus feature-level hooks

You do not need a large framework or agent library here.

The hardest part is not rendering. It is staying disciplined about the backend contract.

## Integration Risks To Watch

- assuming streaming works with `EventSource`
- treating wrapped success payloads like raw JSON
- rebuilding server state on the client
- ignoring `session_mode`
- assuming `owner_type` / `owner_id` is secure auth
- over-coupling the UI to backend trace/debug fields

## Definition Of Done For V1

The frontend is in a good V1 state when a user can:

1. open the app
2. choose catalog or FAQ mode
3. create a thread
4. send a message
5. watch the answer stream in
6. see returned cards when relevant
7. reopen the thread later
8. continue the same conversation

## Next Step

The next engineer should start by:

1. choosing the frontend stack
2. setting up the API client layer
3. implementing the POST-based SSE reader first
4. wiring thread bootstrap before building any “smart” UI

That order matters.
