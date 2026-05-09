# Implementation Plan: `@uaaf/chat-core` + `@uaaf/chat-web` React binding

> **Source handoff**: `tasks/claudechat-handoff-chat-frontend.md` (chat-shell pattern — superseded by chat-core pattern per 2026-05-08 decision).
> **Repo target**: `../uaaf-frontend/` (sibling of `uaaf-framework/`, separate git repo).
> **Backend contract**: `docs/uaaf-framework-spec.md` §SSE event schema (UAAF Python runtime emits `UAAFEvent` stream).

---

## Overview

Build a **framework-agnostic chat client core** + a **thin React binding**. Core is pure TypeScript with zero runtime deps and zero UI assumptions. Bindings (React now, RN/Flutter later) wrap the core.

```
uaaf-frontend/
├── packages/
│   ├── chat-core/           # Pure TS, framework-agnostic, AsyncIterator API
│   │   └── src/
│   │       ├── types.ts            # UAAFEvent, Message, ChatConfig, RetryPolicy
│   │       ├── transport/
│   │       │   └── sse.ts          # parseSSEStream(ReadableStream) → AsyncIterable
│   │       ├── session.ts          # ChatSession class — main entry
│   │       ├── errors.ts           # NetworkError, ParseError, RetryableError, FatalError
│   │       ├── retry.ts            # exponential backoff policy
│   │       └── index.ts            # public exports
│   └── chat-web/            # React binding only — depends on chat-core
│       └── src/
│           ├── useChat.ts          # React hook wrapping ChatSession
│           ├── types.ts            # UseChatState, UseChatActions
│           └── index.ts
├── pnpm-workspace.yaml
├── turbo.json
├── package.json
└── tsconfig.base.json
```

**Scope KHÔNG bao gồm** (defer to later plans):
- UI components (MessageBubble, ThoughtBubble, ToolTracePanel, ErrorBanner, InputBox).
- Product apps (Todo, Stock, Study Buddy, Code Analysis).
- React Native binding (`chat-rn`) and Flutter binding (`chat-flutter`).
- Next.js API route proxy reference impl (apps own this).
- WebSocket price feed (Stock Trading specific).
- File upload (Code Analysis specific).

---

## Architecture Decisions

### AD-1. API shape: `AsyncIterator + Class`
```ts
const session = new ChatSession({ endpoint, sessionId, getAuthHeader })
for await (const ev of session.send("hello")) {
  switch (ev.type) {
    case 'text_delta': /* append */; break
    case 'tool_call':  /* show */;   break
    case 'done':       /* meta */;   break
  }
}
```
**Why**: native JS, zero deps, works identically in Node, browser, RN (Hermes), and Flutter (via JS bridge). Maps 1:1 onto SSE stream semantics. React `useChat` consumes via `for await` inside an async function.
**Trade-off**: consumers without async iteration support (very old runtimes) need transpile — acceptable for our targets (ES2022+).

### AD-2. `chat-core` is pure TS — zero runtime deps, zero `node:*` imports
Only browser/standard APIs: `fetch`, `ReadableStream`, `TextDecoder`, `AbortController`. No `eventsource` lib (custom SSE parser is ~50 LOC and avoids polyfill drama). Allows bundling into RN, Cloudflare Workers, Deno without shims.
**Trade-off**: write our own SSE parser (small, well-tested).

### AD-3. SSE transport via `fetch` + `ReadableStream`
Browser-native. Streams chunks → `TextDecoder` → split on `\n\n` → parse `event:` / `data:` lines → yield `UAAFEvent`.
**Why not `EventSource`?** EventSource doesn't support POST body or custom headers (auth) — both required.

### AD-4. `chat-web` depends on `chat-core` (one-way), `react` is peerDep
`chat-core` never imports React. `chat-web` imports both. Bundle for `chat-web` excludes React. Future `chat-rn` / `chat-flutter` packages follow same one-way rule.

### AD-5. Typed error hierarchy
```ts
class ChatError extends Error { code: string }
class NetworkError extends ChatError      // fetch fail, network drop
class ParseError extends ChatError        // malformed SSE / JSON
class RetryableError extends ChatError    // server hint: retry safe
class FatalError extends ChatError        // server hint: do not retry
```
Mirrors `uaaf.observability.errors` tier on the Python side. Retry policy keys off these classes.

### AD-6. Retry policy injected as interface
```ts
interface RetryPolicy {
  shouldRetry(err: unknown, attempt: number): boolean
  delayMs(attempt: number): number
}
```
Default: `ExponentialBackoffPolicy(max=3, baseMs=500, jitter=0.2)` retries `NetworkError` and `RetryableError`. Caller can swap.
**Why interface**: lets product apps tune (Stock Trading wants fewer retries to fail fast; Code Analysis wants more for long ingest).

### AD-7. `AbortSignal` for cancellation
`session.send(msg, { signal })` accepts AbortSignal. Cancelling closes the stream and breaks the `for await` loop with `AbortError`. Required for "Stop" button in UI and unmount cleanup in React.

### AD-8. History managed in-memory by `ChatSession`
ChatSession holds `messages: Message[]` in memory. On `send()`, sends full history (or last N if `maxHistoryMessages` set in config) to the backend. **Persistence is the consumer's job** (handoff §8 forbids `localStorage` in shared layer).
ChatSession exposes `getHistory()`, `setHistory(msgs)`, `clearHistory()` so consumers can hydrate from their storage of choice (cookie, server, IndexedDB).
**Assumption (Q2)**: backend expects full history per turn (not summary). Mark and revisit if backend spec says otherwise.

### AD-9. Auth via `getAuthHeader()` factory in config
```ts
new ChatSession({
  endpoint,
  getAuthHeader: async () => ({ Authorization: `Bearer ${await getToken()}` })
})
```
Async factory called per request — supports JWT refresh transparently.
**Assumption (Q4)**: bearer token in Authorization header. Mark and revisit when backend auth spec lands.

### AD-10. `structured` event `data` field is **not** parsed by core
Forwarded raw to consumer. Consumer (React component, RN screen) decides how to render. Mirrors handoff §8 constraint.

---

## Phasing

### Phase A — Foundation (T01–T02)
Monorepo + tooling + `chat-core` package skeleton + types. Deliverable: `pnpm install && pnpm build && pnpm test` runs green on empty stubs.

### Phase B — Transport + Session (T03–T04)
SSE parser + `ChatSession.send()` AsyncIterable. Deliverable: against a fake SSE server, `for await` yields all `UAAFEvent` types in order.

### Phase C — Resilience (T05–T06)
Errors, retry, history, auth, abort. Deliverable: network drop mid-stream triggers retry; abort cleanly cancels; history persists across calls.

### Phase D — chat-web React binding (T07–T08)
`useChat` hook wrapping ChatSession. Deliverable: React Testing Library test renders a fake-backed component, sends a message, asserts streaming text + done state.

### Phase E — Verification (T09–T10)
Contract test against a fake UAAF backend matching the spec, integration smoke from `useChat` through SSE end-to-end. Deliverable: CI gate green.

---

## Risks

| # | Risk | Mitigation |
|---|---|---|
| R1 | Backend SSE schema drifts from frontend types | Single source of truth: copy `UAAFEvent` discriminated union from `docs/uaaf-framework-spec.md` verbatim into `types.ts`. Add contract test that parses real backend output. |
| R2 | AsyncIterator + React lifecycle (cleanup, double-mount in StrictMode) | Use `AbortController` per send; cleanup in `useEffect` return; track `mounted` ref to drop late events. Test with React 18 StrictMode enabled. |
| R3 | SSE buffering / chunked-transfer behavior differs across runtimes | Test the parser with split chunks at every byte boundary (property test). Test against Node's `undici` and browser `fetch`. |
| R4 | RN / Flutter bundling later may surface accidental browser-only APIs | Add lint rule banning `window`, `document`, `localStorage`, `sessionStorage`, `node:*` imports in `chat-core/src/`. CI fails on violation. |
| R5 | Open Q1/Q2/Q4/Q6 defaults turn out wrong | All four are isolated behind clean interfaces (storage adapter not in core; history methods on session; auth factory in config; retry policy injected). Swap is local. |

---

## CI gate (per task & at phase boundaries)

- `pnpm typecheck` — TypeScript strict, zero errors.
- `pnpm lint` — ESLint clean (incl. no-restricted-imports rule for `chat-core`).
- `pnpm test` — Vitest, all green, coverage ≥ 80% on `chat-core`, ≥ 70% on `chat-web`.
- `pnpm build` — both packages emit ESM + types; `chat-core` bundle has zero non-peer runtime deps.

---

## Open Questions baked into plan as assumptions

| # | Default chosen | Marker |
|---|---|---|
| Q1 Session storage | `sessionId` injected via config; ChatSession does not persist; consumer wires storage adapter | `// ASSUMPTION-Q1` |
| Q2 Multi-turn history | Full history sent each turn, in-memory, configurable cap | `// ASSUMPTION-Q2` |
| Q4 Auth | `getAuthHeader()` factory returning `Record<string,string>`; default Bearer | `// ASSUMPTION-Q4` |
| Q6 Retry | `RetryPolicy` interface; default exponential backoff max 3 | `// ASSUMPTION-Q6` |
| Q3 File upload | OUT OF SCOPE (UI concern) | n/a |
| Q5 Price feed | OUT OF SCOPE (Stock-specific WebSocket) | n/a |

Each `ASSUMPTION-*` comment site is grep-able so revisits land in the right files when backend spec lands.

---

## Verification checkpoints between phases

- **End of Phase A**: empty `ChatSession` constructable, types compile, build produces dist/.
- **End of Phase B**: full happy-path SSE stream test passes (intent → thought → tool_call → tool_result → text_delta×N → done).
- **End of Phase C**: chaos test passes — kill stream mid-way, retry succeeds; abort mid-stream, no leaks.
- **End of Phase D**: React test renders, types `UseChatState` work in a sample TSX file under strict mode.
- **End of Phase E**: contract test against captured backend fixture runs green; CI gate green.
