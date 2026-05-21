# Todo: `@ryuu/chat-core` + `@ryuu/chat-web`

> **Plan**: `tasks/plan-chat-core.md`
> **Repo**: `../ryuu-frontend/` (separate git repo, sibling of `ryuu-framework/`)
> **Test**: Vitest. **Lint**: ESLint + Prettier. **Build**: tsup. **PM**: pnpm + Turborepo.

CI gate per task: `pnpm typecheck && pnpm lint && pnpm test && pnpm build` all green.

---

## Phase A — Foundation

### T01 — Monorepo bootstrap
- [x] **Acceptance**: `pnpm install` succeeds; `pnpm -r build` builds zero packages cleanly; `pnpm -r test` passes (no tests yet, exits 0).
- [ ] **Verify**: `pnpm typecheck` green, `pnpm lint` green on empty repo.
- [ ] **Files**:
  - `package.json` (root, private, workspaces)
  - `pnpm-workspace.yaml`
  - `turbo.json` (pipeline: `build`, `test`, `lint`, `typecheck`)
  - `tsconfig.base.json` (strict, target ES2022, moduleResolution bundler)
  - `.eslintrc.cjs` + `eslint.config.js` (TS + import rules)
  - `.prettierrc`
  - `.gitignore`
  - `README.md` (one-paragraph repo intent)
- [ ] **Note**: add ESLint `no-restricted-imports` rule banning `window`, `document`, `localStorage`, `sessionStorage`, `node:*` for `packages/chat-core/**`.

### T02 — `chat-core` package skeleton + types
- [x] **Acceptance**: `packages/chat-core` builds; `import { ChatSession } from '@ryuu/chat-core'` resolves; types exported.
- [ ] **Verify**: `pnpm --filter @ryuu/chat-core build` emits `dist/index.js` + `dist/index.d.ts`. Types check strict.
- [ ] **Files**:
  - `packages/chat-core/package.json` (name `@ryuu/chat-core`, type module, peerDependencies empty)
  - `packages/chat-core/tsconfig.json` (extends base)
  - `packages/chat-core/tsup.config.ts`
  - `packages/chat-core/src/types.ts` — `RYUUEvent` (discriminated union, all 9 types from handoff §3), `Message`, `Role`, `ChatConfig`, `RetryPolicy` interface
  - `packages/chat-core/src/session.ts` — empty `ChatSession` class with constructor taking `ChatConfig`
  - `packages/chat-core/src/index.ts` — re-exports
- [ ] **Note**: copy `RYUUEvent` union verbatim from spec to lock contract.

---

## Phase B — Transport + Session

### T03 — SSE parser
- [x] **Acceptance**: `parseSSEStream(stream): AsyncIterable<RYUUEvent>` yields events from a fake `ReadableStream` containing well-formed SSE data.
- [ ] **Verify**: Vitest unit tests cover (a) single event, (b) multiple events, (c) chunks split mid-event, (d) chunks split mid-line, (e) malformed JSON → `ParseError`, (f) unknown event type → `ParseError`.
- [ ] **Files**:
  - `packages/chat-core/src/transport/sse.ts`
  - `packages/chat-core/src/errors.ts` — `ChatError`, `NetworkError`, `ParseError`, `RetryableError`, `FatalError`
  - `packages/chat-core/test/sse.test.ts`
- [ ] **Note**: parser is generator function `async function* parseSSEStream(...)`. Don't depend on `ReadableStream.values()` (Safari gap) — use reader.read() loop.

### T04 — `ChatSession.send()` AsyncIterable happy path
- [x] **Acceptance**: `for await (const ev of session.send("hi"))` against a fake fetch yields full event sequence (intent → thought → tool_call → tool_result → text_delta → done).
- [ ] **Verify**: Vitest test with `vi.spyOn(globalThis, 'fetch')` returning a constructed `Response` whose body is a `ReadableStream` of canned SSE bytes.
- [ ] **Files**:
  - `packages/chat-core/src/session.ts` — implement `send(text: string, opts?): AsyncIterable<RYUUEvent>`; build POST request with `Content-Type: application/json`, body `{ message, sessionId, history }`
  - `packages/chat-core/test/session.send.happy.test.ts`
- [ ] **Note**: tag `// ASSUMPTION-Q2` at the line that builds full-history payload.

---

## Phase C — Resilience

### T05 — Errors + retry policy
- [x] **Acceptance**: `ExponentialBackoffPolicy(max=3, baseMs=500, jitter=0.2)` retries on `NetworkError` and `RetryableError`, gives up after 3 attempts, never retries `FatalError` or `ParseError`.
- [ ] **Verify**: Vitest covers each case. Use `vi.useFakeTimers()` to assert delay between attempts.
- [ ] **Files**:
  - `packages/chat-core/src/retry.ts` — `RetryPolicy` interface + `ExponentialBackoffPolicy` impl
  - `packages/chat-core/src/session.ts` — wrap `send()` request loop in retry policy
  - `packages/chat-core/test/retry.test.ts`
- [ ] **Note**: tag retry default site with `// ASSUMPTION-Q6`.

### T06 — History + auth + abort
- [x] **Acceptance**:
  - `session.getHistory() / setHistory() / clearHistory()` work; sent payload includes prior turns.
  - `getAuthHeader()` factory called per request; resolved headers merged into fetch.
  - `session.send(msg, { signal })` aborts cleanly: stream closes, `for await` throws `AbortError`, no unhandled promise rejections.
- [ ] **Verify**: 3 separate Vitest cases.
- [ ] **Files**:
  - `packages/chat-core/src/session.ts` — extend
  - `packages/chat-core/test/session.history.test.ts`
  - `packages/chat-core/test/session.auth.test.ts`
  - `packages/chat-core/test/session.abort.test.ts`
- [ ] **Note**: tag auth site with `// ASSUMPTION-Q4`, history persistence boundary with `// ASSUMPTION-Q1`.

---

## Phase D — chat-web React binding

### T07 — `chat-web` package skeleton + `useChat` hook
- [x] **Acceptance**:
  ```tsx
  const { messages, streaming, send, error, abort } = useChat({ endpoint })
  ```
  works; calling `send("hi")` updates `messages` state token-by-token; `streaming` flips true → false; cleanup on unmount aborts.
- [ ] **Verify**: React Testing Library test with `@testing-library/react` + `jsdom`. Mock fetch with a streamed response. Assert state transitions. Run with React 18 StrictMode.
- [ ] **Files**:
  - `packages/chat-web/package.json` (peer dep `react: ^18 || ^19`, dep `@ryuu/chat-core: workspace:*`)
  - `packages/chat-web/tsconfig.json`
  - `packages/chat-web/src/useChat.ts`
  - `packages/chat-web/src/types.ts` — `UseChatState`, `UseChatActions`
  - `packages/chat-web/src/index.ts`
  - `packages/chat-web/test/useChat.test.tsx`
  - Vitest config: jsdom env for `chat-web`, node env for `chat-core`.
- [ ] **Note**: use `useRef` for `ChatSession` (single instance per component); `AbortController` per send; cleanup on unmount.

### T08 — chat-web event mapping coverage
- [x] **Acceptance**: every `RYUUEvent` type maps to expected state mutation: `text_delta` appends to last assistant message; `thought` accumulates in `thoughts[]`; `tool_call` pushes to `toolTrace[]`; `error` sets `error`; `done` sets `meta` and clears `streaming`; `structured` exposes raw `data` via `structuredPayload` for caller render.
- [ ] **Verify**: parameterized test, one case per event type.
- [ ] **Files**:
  - `packages/chat-web/src/useChat.ts` — extend
  - `packages/chat-web/test/useChat.events.test.tsx`

---

## Phase E — Verification

### T09 — Contract test against captured fixture
- [x] **Acceptance**: a recorded SSE byte stream from the real RYUU Python backend (or a hand-crafted fixture matching spec verbatim) replays through `ChatSession` and produces an expected sequence.
- [ ] **Verify**: snapshot test of yielded events.
- [ ] **Files**:
  - `packages/chat-core/test/fixtures/full-conversation.sse` (raw bytes)
  - `packages/chat-core/test/contract.test.ts`
- [ ] **Note**: until backend is reachable, hand-craft fixture to match `docs/ryuu-framework-spec.md` event schema. Replace with real capture once available.

### T10 — Integration smoke (chat-web ↔ chat-core)
- [x] **Acceptance**: a smoke test renders a tiny React component that uses `useChat`, sends a message against a fake fetch backed by the fixture, asserts final UI state matches expectation.
- [ ] **Verify**: passes in CI under both Node 20 and Node 22.
- [ ] **Files**:
  - `packages/chat-web/test/integration.smoke.test.tsx`
  - `.github/workflows/ci.yml` — typecheck + lint + test + build matrix on Node 20/22.

---

## Done definition for this plan

- All 10 tasks checked.
- CI gate green: `pnpm typecheck && pnpm lint && pnpm test && pnpm build`.
- Coverage ≥ 80% on `chat-core`, ≥ 70% on `chat-web`.
- `chat-core` dist has zero non-peer runtime deps (verify via `pnpm why` and bundle inspection).
- README in each package has a 5-line "how to consume" example.
- All `// ASSUMPTION-Q*` comments are grep-able and listed in plan.
