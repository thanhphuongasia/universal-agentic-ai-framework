# Handoff: Chat Frontend — RYUU Chat Shell

> **Dành cho**: Claude Code
> **Mục tiêu**: Lên implementation plan cho shared chat frontend component dùng chung giữa các RYUU product
> **Context**: Đây là frontend layer của hệ thống RYUU (Universal Agentic AI Framework). Backend đã có spec đầy đủ tại `ryuu-framework-spec.md`.

---

## 1. Bối cảnh — tại sao cần Chat Shell

RYUU có nhiều product: Todo App, Study Buddy, Stock Trading, Code Analysis. Mỗi product là một app end-user riêng biệt, deploy độc lập. Tất cả đều có giao diện chat là interaction chính.

Phần chat của mỗi product **giống nhau về cấu trúc**, **khác nhau về cách render output**:

| | Todo App | Study Buddy | Stock Trading | Code Analysis |
|---|---|---|---|---|
| **Input** | Text | Text | Text | Text + file upload |
| **Output** | Text | Text + flashcard | Text + chart | Text + diagram + code block |
| **Action đặc thù** | Create task từ chat | Tạo deck ôn tập | Place order button | Show dependency graph |
| **External data feed** | Không cần | Không cần | Cần (price feed WebSocket) | Không cần |
| **Auth context** | User session | User session | User session + compliance disclaimer | User session |

> **Lưu ý quan trọng**: Streaming (token by token, thought bubble, tool trace) thì **tất cả product đều cần**. "External data feed" mới là thứ chỉ Stock Trading cần.

---

## 2. Quyết định kiến trúc đã được confirm

### 2.1 Deployment model
Mỗi product deploy riêng — RYUU Python runtime riêng, Next.js app riêng. Không có shared runtime instance.

### 2.2 Tech stack
- **Frontend**: React / Next.js (App Router)
- **Monorepo**: Turborepo hoặc nx
- **Shared package**: `@ryuu/chat-shell` — npm package nội bộ, không publish public
- **Streaming protocol**: SSE (Server-Sent Events) cho chat stream, WebSocket cho Stock Trading price feed

### 2.3 Pattern: Slot pattern
ChatShell là khung cố định. Product inject renderer riêng qua props:

```tsx
// packages/chat-shell — shared
interface ChatShellProps {
  apiEndpoint: string
  renderMessage: (message: Message) => ReactNode   // slot bắt buộc
  renderActions?: (message: Message) => ReactNode  // slot optional
  config?: ChatConfig
}
```

---

## 3. Event schema — contract giữa RYUU backend và frontend

RYUU backend phát ra các event qua SSE stream. Frontend consume và render tương ứng:

```typescript
type RYUUEvent =
  | { type: 'intent_classified'; intent_type: string; confidence: number }
  | { type: 'strategy_selected'; strategy: string }
  | { type: 'thought'; content: string }
  | { type: 'tool_call'; tool: string; args: unknown }
  | { type: 'tool_result'; tool: string; result: unknown; duration_ms: number }
  | { type: 'text_delta'; content: string }
  | { type: 'structured'; renderer: string; data: unknown }
  | { type: 'error'; code: string; message: string }
  | { type: 'done'; cost_usd: number; duration_ms: number; tokens_used: number }
```

**Mapping event → UI component** (ChatShell xử lý, product không cần biết):

| Event | Component | Behavior |
|---|---|---|
| `intent_classified` | IntentBadge | Hiện nhỏ phía trên message, fade sau 3s |
| `strategy_selected` | StrategyBadge | Hiện nhỏ, collapsible |
| `thought` | ThoughtBubble | Collapsible, italic, màu muted |
| `tool_call` + `tool_result` | ToolTracePanel | Expand/collapse, hiện tool name + duration |
| `text_delta` | MessageBubble | Stream in từng token |
| `structured` | → `renderMessage` prop | Forward xuống product renderer |
| `error` | ErrorBanner | Inline trong chat, có retry button |
| `done` | MetadataFooter | Cost + duration, hiện nhỏ dưới message |

---

## 4. Repo structure mong muốn

```
ryuu-frontend/
├── packages/
│   └── chat-shell/
│       ├── src/
│       │   ├── ChatShell.tsx           # root component
│       │   ├── components/
│       │   │   ├── MessageList.tsx
│       │   │   ├── MessageBubble.tsx   # stream in text_delta
│       │   │   ├── ThoughtBubble.tsx
│       │   │   ├── ToolTracePanel.tsx
│       │   │   ├── InputBox.tsx        # text input + send button
│       │   │   ├── FileUpload.tsx      # optional, Code Analysis dùng
│       │   │   └── ErrorBanner.tsx
│       │   ├── hooks/
│       │   │   ├── useChat.ts          # SSE stream logic chính
│       │   │   ├── useSession.ts       # session management
│       │   │   └── useScrollAnchor.ts  # auto scroll to bottom
│       │   └── types.ts               # RYUUEvent types, Message types
│       ├── package.json
│       └── tsconfig.json
│
└── apps/
    ├── todo/
    │   └── src/
    │       ├── app/api/chat/route.ts   # Next.js API route → RYUU backend
    │       └── components/
    │           └── TodoMessageRenderer.tsx
    ├── stock-trading/
    │   └── src/
    │       ├── app/api/chat/route.ts
    │       ├── components/
    │       │   ├── StockMessageRenderer.tsx
    │       │   └── ChartPanel.tsx
    │       └── hooks/
    │           └── usePriceFeed.ts     # WebSocket riêng cho price feed
    ├── study-buddy/
    └── code-analysis/
        └── src/
            ├── app/api/chat/route.ts
            └── components/
                ├── CodeMessageRenderer.tsx
                ├── DiagramViewer.tsx
                └── CodeBlock.tsx
```

---

## 5. Luồng data end-to-end

```
Browser                    Next.js API Route         RYUU Python Runtime
   │                              │                          │
   │── POST /api/chat ───────────▶│                          │
   │   { message, session_id }    │── HTTP POST ────────────▶│
   │                              │                          │ IntentTier
   │◀── SSE stream open ──────────│                          │ StrategySelector
   │                              │                          │ AgentPool
   │◀── event: intent_classified ─│◀── SSE forward ──────────│
   │◀── event: thought ───────────│◀── SSE forward ──────────│
   │◀── event: tool_call ─────────│◀── SSE forward ──────────│
   │◀── event: tool_result ───────│◀── SSE forward ──────────│
   │◀── event: text_delta ────────│◀── SSE forward ──────────│ (nhiều lần)
   │◀── event: structured ────────│◀── SSE forward ──────────│ (nếu có)
   │◀── event: done ──────────────│◀── SSE forward ──────────│
```

**Next.js API Route** chỉ là thin proxy — nhận SSE từ RYUU Python, forward ra browser. Không có business logic ở đây.

```typescript
// Pattern cho tất cả apps
export async function POST(req: Request) {
  const body = await req.json()
  const ryuuResponse = await fetch(process.env.RYUU_BACKEND_URL + '/chat/stream', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body)
  })
  // forward stream thẳng ra
  return new Response(ryuuResponse.body, {
    headers: { 'Content-Type': 'text/event-stream' }
  })
}
```

---

## 6. Các điểm cần plan cụ thể

Claude Code cần lên plan cho các phần sau, theo thứ tự ưu tiên:

### Phase A — Foundation (làm trước)
1. **Monorepo setup**: Turborepo config, workspace linking, shared tsconfig
2. **`types.ts`**: Định nghĩa đầy đủ `RYUUEvent`, `Message`, `ChatConfig` types
3. **`useChat.ts` hook**: SSE connection, parse event stream, state management
4. **`ChatShell.tsx`**: Root component với slot pattern, wire tất cả sub-components
5. **`InputBox.tsx`**: Text input, submit, loading state, disable khi streaming

### Phase B — Event rendering (làm sau Phase A)
6. **`MessageBubble.tsx`**: Stream in text_delta từng token, markdown render
7. **`ThoughtBubble.tsx`**: Collapsible, hiện/ẩn thought stream
8. **`ToolTracePanel.tsx`**: Tool call + result, expand/collapse, duration badge
9. **`ErrorBanner.tsx`**: Error display + retry logic

### Phase C — Product renderers (mỗi product tự làm, dùng Phase A+B)
10. **Code Analysis**: `DiagramViewer`, `CodeBlock` renderer
11. **Stock Trading**: `ChartPanel` renderer + `usePriceFeed` WebSocket hook
12. **Study Buddy**: `FlashcardPreview` renderer
13. **Todo App**: `TaskCard` renderer (đơn giản nhất — làm reference implementation)

---

## 7. Open questions cần quyết định trước khi code

| # | Câu hỏi | Tác động |
|---|---|---|
| Q1 | Session storage ở đâu? Cookie, localStorage, hay server-side? | `useSession.ts` design |
| Q2 | Có cần conversation history (multi-turn) không? Nếu có, send full history hay summary? | `useChat.ts` payload |
| Q3 | File upload (Code Analysis) — upload trực tiếp lên RYUU hay qua presigned S3? | `FileUpload.tsx` + API route |
| Q4 | Auth: JWT hay session cookie? RYUU backend expect header gì? | API route middleware |
| Q5 | Stock Trading price feed — WebSocket URL là gì, reconnect strategy thế nào? | `usePriceFeed.ts` |
| Q6 | Error retry: auto retry hay manual? Sau bao nhiêu lần thì stop? | `ErrorBanner.tsx` + `useChat.ts` |

---

## 8. Constraints

- **Không dùng** `localStorage` hay `sessionStorage` trong ChatShell — không work trong một số deployment context. Dùng React state hoặc server-side session.
- **Không có business logic** trong Next.js API route — chỉ proxy.
- **ChatShell không import** bất cứ thứ gì từ domain của product cụ thể. Dependency chỉ một chiều: apps → chat-shell.
- **`structured` event**: ChatShell không parse `data` field — forward nguyên xi xuống `renderMessage` prop. Product tự parse.

---

## Changelog

| Date | Note |
|---|---|
| 2026-05-08 | Tạo handoff document từ design review session |
