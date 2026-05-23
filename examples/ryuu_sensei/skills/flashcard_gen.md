---
name: flashcard_gen
description: Tạo flashcard học bài (Q/A pairs) từ một chủ đề, đoạn ghi chú, hoặc bài viết
triggers:
  - "tạo flashcard"
  - "tạo card"
  - "make flashcards"
  - "anki cards"
  - "tạo thẻ học"
requires_tools: []
---

# Flashcard Generator — StudyBuddy style

## Khi nào áp dụng

- User gửi nội dung (đoạn note, code snippet, định nghĩa) + yêu cầu tạo flashcard.
- User paste link / dùng `article_summary` skill rồi nói "tạo flashcard từ bài trên".
- User nói "ôn lại X, tạo card cho tôi".

## Steps

1. **Identify scope** — Đếm xem nội dung có bao nhiêu concept tách biệt. Một concept = một card.
2. **Apply quality rules** (rất quan trọng, xem section bên dưới).
3. **Output theo format** — JSON array, mỗi card 1 object.

## Quality Rules (BẮT BUỘC)

- **One concept per card.** Không gộp 2 ý vào 1 card. Nếu 1 ý có 2 phần → tách 2 cards.
- **Question testable.** Đọc xong câu hỏi phải đoán được câu trả lời mà không cần nhìn code/note.
- **Answer 3–8 dòng** (max 12). Đủ để stand alone khi review, không phải re-read.
- **Có "dùng khi nào" / why it matters** — context không bị mất.
- **Code blocks** dùng fenced ` ```python `, ` ```csharp ` v.v. Không inline backtick cho multi-line.
- **Junior-friendly** — tránh jargon không giải thích. Dùng analogy nếu giúp (ví dụ "như queue trong quán cafe").

## Output Format

```json
[
  {
    "front": "<question — clear, testable>",
    "back": "<answer — 3–8 lines, fenced code if any>",
    "tags": ["<topic>", "<sub-topic>"],
    "why_matters": "<1 dòng — dùng khi nào, tại sao quan trọng>"
  },
  ...
]
```

## Lỗi thường gặp (tránh)

- ❌ Gộp "What is X and how does it work?" → tách 2 cards: "What is X?" + "How does X work?".
- ❌ Câu trả lời chỉ 1 dòng "Yes" / "It's a thing" → mở rộng.
- ❌ Câu trả lời 20 dòng → cắt xuống <12 dòng, giữ essence.
- ❌ Không có code example khi concept là về code → thêm minimal snippet.
- ❌ Tags rỗng hoặc quá chung (#code) → cụ thể (#python #async).

## Ví dụ một card đúng

```json
{
  "front": "Tại sao Python `async def` cần `await` khi gọi function async khác?",
  "back": "Coroutine không tự chạy — `await` hand control về event loop và đợi result.\n\nVí dụ:\n```python\nasync def fetch():\n    data = await get_data()  # ← await, không gọi như sync\n    return data\n```\n\nNếu quên `await`, bạn get coroutine object (không phải kết quả) → bug.",
  "tags": ["python", "async-await", "coroutine"],
  "why_matters": "Dùng khi viết bất kỳ async code Python — hiểu lifetime của coroutine."
}
```
