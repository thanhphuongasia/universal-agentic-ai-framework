# Plan — CRUD Review Matrix (modular, progress-tracking-ready)

**Date:** 2026-05-30
**Goal:** Tab 4 (Review & Approve) hiển thị CRUD dạng **bảng tương tác chia module theo entity**,
mỗi cell có edit(op)/approve/delete. Non-CRUD giữ `CellsView` read-only.

## Chốt với user
- Edit scope = **chỉ OP** → map action `fix` (`corrected_op`), không đổi backend.
- Layout = **chia module theo entity** (section collapse được) + progress per-section + tổng. Chừa hook tracking sau.
- Non-CRUD → `CellsView` cũ.

## Phát hiện then chốt
`POST /oracle-review/{fixture_id}/review` (router.py:2075) áp action lên **toàn bộ `expected`**, không
giới hạn `needs_review` → approve/fix/remove trên cell high-confidence ĐÃ chạy được. Core feature = frontend-only.

## Hai vấn đề
- **A. Bug `$FUNCTION_NAME`:** oracle emit key placeholder → `expected` dư 1 tầng → `needs_review` rỗng + CRUD detect fail → JSON fallback (chính là screenshot).
- **B. Feature:** bảng review tương tác, modular.

## Component (mới): `web/src/components/oracle/review/`
- `reviewModel.ts` — logic thuần: `unwrapCells`, `buildRows`, `groupByEntity`, `computeProgress`, `isCrudReviewable`.
- `CrudReviewMatrix.tsx` — orchestrator: detect CRUD → sections + progress; else `<CellsView>`.
- `ReviewSection.tsx` — 1 entity, collapse, header progress mini, "Approve all in entity".
- `CrudReviewRow.tsx` — 1 field: OP (inline edit) · Conf · Why · Status · [✓ ✏ 🗑].
- `ReviewProgress.tsx` — progress bar tổng + filter chips. Hook cho tracking sau.

## Data model
Nguồn = `fixture.expected` (mọi cell). Overlay `review_items` + `pendingActions`.
`RowVM{entity,field,op,confidence,why,needsReview,effectiveAction,status}`.
status: high→`auto`; low/medium chưa xử lý→`pending`; có action→`approved|fixed|removed`.

## Tasks
- **T0 (backend):** `_get_cells`/`_normalize_fixture_for_ui` unwrap 1-key wrapper khi value là CRUD 2-tầng. Verify: `studio_test_post_orders` → review_items có medium, expected 2 tầng.
- **T1:** `reviewModel.ts` (unwrap/buildRows/groupByEntity/computeProgress/isCrudReviewable).
- **T2:** unit test reviewModel (2-tầng, wrapper, overlay, progress, non-CRUD=false).
- **T3:** `CrudReviewRow.tsx` (inline edit OP, 3 nút).
- **T4:** `ReviewSection.tsx` (collapse + header progress).
- **T5:** `ReviewProgress.tsx` (bar + filter; hook tracking).
- **T6:** `CrudReviewMatrix.tsx` (detect → sections | CellsView fallback).
- **T7:** wire vào `Tab4_Review` (thay cả 2 nhánh), giữ Save/Promote/reviewer.
- **T8:** tính lại `pendingCount` = low/medium chưa resolve (từ computeProgress).
- **T9:** regression non-CRUD → CellsView.
- **T10:** build + smoke localhost:5173.

## Out of scope
- Edit confidence/why (chỉ OP).
- Multi-input `inputs[]`: lần này input đơn/inputs[0], ghi TODO.

## Tracking (tương lai)
`ReviewProgress` nhận `Progress` thuần → sau thêm per-cell reviewed_at/by, persist, stepper header.
