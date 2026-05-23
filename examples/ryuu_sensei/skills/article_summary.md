---
name: article_summary
description: Tóm tắt bài viết từ URL theo template chuẩn (TL;DR + Key Points + Bài học + Caveats)
triggers:
  - "tóm tắt bài"
  - "summarize this"
  - "tldr"
  - "tóm tắt link"
  - "summarize the article"
requires_tools:
  - fetch_fetch
---

# Article Summary — Standard Template

## Khi nào áp dụng

- User paste 1 URL (https://...) kèm yêu cầu tóm tắt
- User nói rõ "tóm tắt bài", "summarize", "tldr", v.v.
- User hỏi key points / bài học từ một bài cụ thể

## Steps

1. **Fetch content** — Gọi `fetch_fetch(url=...)` để lấy nội dung HTML đã convert sang markdown.
2. **Identify metadata** — Trích tiêu đề, tác giả (nếu có), nguồn (domain).
3. **Synthesize** — KHÔNG paraphrase từng câu. Đọc toàn bộ, rút key insights.
4. **Output theo template bên dưới**.

## Output Format (markdown — strict)

```
📰 **Tiêu đề:** <title>
✍️ **Tác giả / Nguồn:** <author or domain>
🔗 **Link:** <url>

**📌 TL;DR (2–3 câu):**
<gist — bài này nói gì, kết luận chính>

**🎯 Key Points (3–6 bullets):**
- <điểm 1 — concrete, không abstract>
- <điểm 2>
- <điểm 3>
- ...

**💡 Bài học rút ra (2–4 bullets):**
- <lesson 1 — apply cho công việc / cuộc sống thế nào>
- <lesson 2>
- ...

**⚠️ Điểm cần chú ý / Counter-points:**
- <claim đáng nghi, thiếu dữ liệu, bias của tác giả nếu có>
- <hoặc viết "Không phát hiện điểm đáng nghi" nếu bài chắc chắn>

**🏷️ Tags:** #topic1 #topic2 #topic3
```

## Style guidelines

- Viết tiếng Việt (trừ khi user dùng tiếng Anh).
- Key points = **insight**, không phải tóm tắt cấu trúc bài ("phần 1 nói về…, phần 2 nói về…" là SAI).
- Bài học phải actionable — "nên làm X khi gặp Y", không phải "tốt", "hay".
- Counter-points trung thực — nếu bài có claim quá mạnh hoặc thiếu dữ liệu, gọi tên ra.
- Không sao chép nguyên câu từ bài — tổng hợp lại bằng giọng tự nhiên.

## Lỗi thường gặp (tránh)

- ❌ Bullet quá dài 2-3 dòng → mỗi bullet 1 câu súc tích.
- ❌ "Bài viết rất hay" / "rất bổ ích" → vô nghĩa.
- ❌ Tags chung chung như #life #tech → cụ thể hơn (#productivity #async-work).
- ❌ Bỏ qua counter-points để giữ tone tích cực → mất giá trị critical thinking.
