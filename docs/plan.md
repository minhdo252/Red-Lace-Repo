# PLAN: Sửa backend để Voice detect được price scam ("cô bán bún chả này 200k")

> **✅ ĐÃ IMPLEMENT & VERIFY (2026-07-19).** Nhánh voice giờ chạy so giá tham chiếu như route ảnh.
> Đã sửa: `backend/app/config.py`, `backend/app/routers/chat.py`. Thêm mới:
> `backend/app/modules/transcript_price_extract.py`, `backend/tests/test_voice_price_check.py`.
> Cập nhật test: `test/chat_routing_test.py`, `test/module13_synthetic/dataset.json`.
>
> Verify đã chạy: `py_compile` OK toàn bộ file Python; JSON dataset hợp lệ; **8/8 case trích (món, giá)
> chạy trên code thật** đều PASS — gồm đúng ví dụ "cô bán bún chả này 200k" → `("bún chả", 200000)`,
> nhánh đánh vần "hai trăm nghìn", chặn số điện thoại, gate không-giá, và guard chống LLM bịa giá.
> `test_voice_price_check.py` (10 case) + `chat_routing_test.py` cần chạy trong Docker/Railway CI
> (máy local thiếu fastapi/qdrant/asyncpg và không có Docker).

## 1. Context — Tại sao voice "chưa hoạt động"

Voice **đã transcribe được** (MediaRecorder webm → `POST /api/chat` → backend `/chat` với `audio_base64`
→ STT FPT Whisper ở `backend/app/ai/client.py::AIClient.transcribe`). Vấn đề: routing theo loại input
(`backend/app/routers/chat.py:648`) đưa audio vào nhánh **voice**, mà nhánh voice **chỉ** gather
`_translate_for_chat + _scan_scam_prefilter + detect_threat` — **không gọi `compare_price`**. Nên
"cô bán bún chả này 200k" được trích giá `[200000]` nhưng **không so với giá bún chả tham chiếu**
(~59–69k trong seed → 200k là +~220%) → không có cảnh báo scam. Regex prefilter (`FALLBACK_SCAM_RULES`)
cũng không bắt "món + giá" đơn thuần (yêu cầu km / 500k–900k+pay / "too expensive"). `compare_price`
(`price_comparison.py:147`) trước đó chỉ nối vào route **image** và **text**.

Frontend KHÔNG cần sửa: `frontend/src/lib/api.ts::verdictFor` hiện badge "scam" khi `scam_flags[].best_score >= 0.72`,
schema response đã có sẵn `price_analysis`/`scam_flags`/`tools_invoked`.

**Vận hành khi deploy:** backend Railway cần `AI_MODE=live` + `AI_STT_API_KEY` (đã set); frontend Vercel cần
`BACKEND_URL` (đã set). Thiếu → Translate rơi im lặng về mock taxi.

## 2. Đã thay đổi

**`backend/app/config.py`** — thêm `price_check_deadline_seconds: int = 10` vào block latency budgets.

**`backend/app/modules/transcript_price_extract.py`** (MỚI) — trích cặp (món, giá) từ transcript:
- `extract_priced_items(text)` async: gate bằng `extract_normalized_prices_vnd` (rỗng → `[]`, 0 latency);
  primary gọi GLM (`ai_client.chat` JSON) → chỉ nhận giá nằm trong tập giá tất định (chống hallucination);
  fallback `heuristic_priced_items` khi GLM lỗi/mock/không ra cặp hợp lệ.
- `heuristic_priced_items(text)` tất định: định vị token giá trên bản fold dấu, nhìn lùi ≤6 token tìm token
  đầu món trong `price_comparison._COMPOUND_STARTERS` (khớp trên token **có dấu**, loại token vừa-là-số như "ba"),
  ghép head 1–2 token, clean bằng `menu_normalize.normalize_item_name`.

**`backend/app/routers/chat.py`**:
- `_analysis_item(item_name, observed, comparison)` — factor dict verdict dùng chung image + voice.
- `_PRICE_WARNING_TEMPLATES` (vi/en/ko/zh/ja) + `_price_warning_note` + `_price_flag_text`.
- `_run_voice_price_check(text, region, native_language)` — bọc `asyncio.wait_for(price_check_deadline_seconds)`,
  never-raises; trích cặp → `compare_price` từng món (category "food") → build `price_analysis`; nếu có món bị
  `flag` thì thêm scam flag `{category: price_scam, best_score: 0.9 nếu diff≥80% còn lại 0.75, source: price_comparison}`
  + `reply_note` theo native_language. Lỗi/timeout → envelope rỗng + `degraded`.
- Nhánh voice: thêm task thứ 4 vào `asyncio.gather`, `_merge_scam_flags` gộp price flag, set `price_analysis`/
  `tools_invoked`, nối `reply_note` vào `reply`, thêm `"price_check"` vào `degraded_components` khi degrade.
  Chạy trên `clean_text` (tiếng Việt gốc) → song song hoàn toàn với dịch.

**Tests:** `test/chat_routing_test.py` nới assert voice `tools_invoked` thành `<= {"compare_price"}`;
`test/module13_synthetic/dataset.json` W009 (bún chả 120k) thêm `"expected_scam": "price_scam"`;
`backend/tests/test_voice_price_check.py` (MỚI, 10 case).

## 3. Trace "cô bán bún chả này 200k" (voice, live)
STT → "Cô bán bún chả này 200k" → route voice → gather{dịch `[200000]`, prefilter (miss, đúng), threat NONE,
price check: gate `[200000]` → GLM/heuristic `[("bún chả",200000)]` → `compare_price` kNN Hanoi/food ref ~62k →
+222% > 30% → flag}. Response: `price_analysis.overall_overpriced=true`; `scam_flags` có price_scam 0.9;
`reply` = bản dịch + cảnh báo. Frontend: 0.9 ≥ 0.72 → badge **"scam"**.

## 4. Verification / Deploy

**Local (không cần stack):** `cd backend && python tests/test_voice_price_check.py`
**Mock toàn stack:** `docker compose up --build` rồi `python test/chat_routing_test.py`
**Live curl (đã seed):**
```bash
curl -s -X POST <backend>/chat/text -H 'content-type: application/json' \
  -d '{"session_id":"<SID>","text":"cô bán bún chả này 200k","region":"Hanoi","speaker_role":"vendor"}'
# audio thật: POST /chat với audio_base64 fixture w009 → input_route=voice, price_analysis.overall_overpriced=true
python test/module13_synthetic/run_dataset.py --suite audio
```
**Deploy backend (Railway, env đã set):** `cd backend && railway up --service nonai-backend`
(cần `railway login` tương tác nếu chưa đăng nhập). Frontend không đổi → không cần deploy lại Vercel.

## 5. Rủi ro đã cân nhắc
Category hardcode "food" (taxi/tour rơi web fallback; prefilter đã cover taxi); web fallback có thể ăn budget
(deadline 10s chặn); double-flag `_merge_scam_flags` giữ score cao hơn; import hàm underscore-private (có tiền lệ
`run_dataset.py`); W009 expectation phụ thuộc seed live.
