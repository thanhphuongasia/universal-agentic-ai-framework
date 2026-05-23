---
name: email_summary
description: Tóm tắt email / newsletter đầy đủ — agent đọc toàn bộ nội dung email qua Gmail MCP, trích xuất tất cả story/item, không bỏ sót
triggers:
  - "tóm tắt email"
  - "summarize the email"
  - "tóm tắt newsletter"
  - "summarize newsletter"
  - "đọc email"
  - "email hôm nay"
  - "có gì trong email"
requires_tools:
  - gmail_get_email
  - gmail_list_emails
---

# Email Summary — Full Coverage

## Khi nào áp dụng

- Agent vừa nhận được email ID / thread để tóm tắt
- User hỏi "email hôm nay có gì", "tóm tắt email X"
- Email là newsletter dạng digest (nhiều tin trong 1 email)

## Steps

1. **Đọc toàn bộ email** — Gọi `gmail_get_email` với email ID. Đọc **toàn bộ body**, không dừng ở preview hay snippet.
2. **Identify metadata** — Subject, sender, date từ email header.
3. **Phân loại email**:
   - *Newsletter/digest*: có nhiều story/section riêng biệt → mỗi story = 1 bullet Key Point
   - *Single-topic email*: 1 chủ đề → tóm tắt như article
4. **Đọc hết các link nếu cần** — Nếu email chứa link "Read more" / "Full story" và nội dung trong email bị cắt, gọi `fetch_fetch(url=...)` để lấy nội dung đầy đủ.
5. **Synthesize toàn bộ** — Không bỏ bất kỳ story/section quan trọng nào. Quảng cáo và survey link thì bỏ qua.
6. **Output theo template bên dưới**.

## Output Format (markdown — strict)

```
📧 **Subject:** <subject line>
✍️ **Từ:** <sender name / newsletter name>
📅 **Ngày:** <date>

**📌 TL;DR (2–3 câu):**
<tóm gọn email nói về gì — nếu là digest thì nêu chủ đề bao quát>

**🎯 Key Points:**
- <story/item 1 — tên, điểm chính, số liệu quan trọng nếu có>
- <story/item 2>
- <story/item 3>
- ... (liệt kê TẤT CẢ story, không giới hạn số lượng)

**💡 Đáng chú ý nhất:**
- <1–2 điểm thực sự nổi bật — ảnh hưởng lớn, số liệu bất ngờ, hoặc liên quan trực tiếp đến công việc của user>

**⚠️ Điểm cần kiểm chứng:**
- <claim thiếu dữ liệu, nguồn không rõ, hoặc "Không có điểm đáng nghi">

**🏷️ Tags:** #topic1 #topic2
```

## Quy tắc quan trọng

- **ĐỌC HẾT** body email trước khi tóm tắt — không dừng sau đoạn đầu tiên.
- Với newsletter digest: mỗi story là 1 bullet riêng, dù story ngắn.
- Bỏ qua: quảng cáo (Presented by / Sponsored), survey link, unsubscribe footer.
- Số liệu cụ thể (doanh thu, %, ngày tháng) phải giữ nguyên — đây là phần có giá trị nhất.
- Không viết "email rất hay / bổ ích" — vô nghĩa.

## Lỗi thường gặp (tránh)

- ❌ Chỉ tóm tắt đoạn mở đầu (intro paragraph) rồi dừng.
- ❌ Bỏ qua các story phía dưới vì "đã đủ key points rồi".
- ❌ Lẫn lộn nội dung quảng cáo với tin tức thật.
- ❌ Key Points chỉ có 3 bullets trong khi email có 6 story riêng biệt.
