# AITravelMate (Nón AI) — Tóm tắt kiến trúc & roadmap MVP 48h

**Sản phẩm:** trợ lý ảo kiêm phiên dịch đa ngôn ngữ (English, Mandarin, Korean — mở rộng sau) đi cùng khách du lịch, phát hiện bất thường/lừa đảo trong mua bán dịch vụ du lịch (giá cả, ghost tour/homestay), và kết nối hỗ trợ khẩn cấp (y tế, công an, đại sứ quán).
**Địa điểm MVP:** Hà Nội, Sapa, Hội An.
**3 module:** (1) Dịch thuật, (2) Scam detector — 2.1 giá cả / 2.2 ghost tour & homestay, (3) Emergency.

---

## 1. Tech stack tổng hợp

| Thành phần | Lựa chọn | Ghi chú |
|---|---|---|
| Vector DB | **Qdrant** (Docker local hoặc Qdrant Cloud free tier) | Chỉ lưu vector + payload lọc (region/category). Không lưu số liệu giá/thống kê ở đây. |
| Structured DB | **Postgres** (khuyến nghị Supabase free tier — zero-ops) | Lưu `price_references`, `geo_regions`, `emergency_hotlines`, `embassies`, session config |
| Backend | FastAPI (Python) | |
| LLM (reasoning + vision) | Gemini Flash / GPT-4o-mini | Multimodal (đọc ảnh) + function/tool calling native |
| STT | Whisper (multilingual, large-v3) | Đủ mạnh cho EN/Mandarin/Korean, có language hint |
| TTS | Google Cloud TTS hoặc ElevenLabs | Chọn 1, ưu tiên latency thấp hơn chất lượng giọng |
| Embedding | sentence-transformer đa ngôn ngữ (local) hoặc embedding API | Dùng để tạo vector đẩy vào Qdrant |
| Domain intelligence | `python-whois` hoặc WhoisXML API | Check tuổi domain cho module 2.2 |
| Business existence check | Google Places API | Rating, review count, 5 review gần nhất |
| Telephony (SOS) | `tel:` link (MVP tối thiểu) hoặc Twilio Voice (nếu muốn polish demo) | STT-trong-cuộc-gọi = Phase 2, không làm trong 48h |
| Frontend | Web app nhẹ (hoặc Telegram Mini App) | "Login + chọn ngôn ngữ" cần UI thật, khó làm gọn bằng thuần chat bot |

**Nguyên tắc tách dữ liệu:** Qdrant chỉ trả lời "text này giống gì nhất" (item name, scam pattern). Mọi số liệu (giá, thống kê Bayesian, hotline) sống ở Postgres. Qdrant point chỉ giữ payload trỏ ngược về id trong Postgres — tránh đồng bộ 2 nguồn sự thật.

---

## 2. Nguyên tắc cắt scope cho 48h

| Hạng mục gốc | Quyết định cho 48h |
|---|---|
| Crawler thật (Google Maps/TripAdvisor/ShopeeFood/Grab) | Bỏ cho bản lõi. Nhập tay + LLM synthetic data cho giá/món 3 địa điểm. Đánh dấu crawler thật là Phase 2 |
| Geo_Regions polygon/PostGIS | Bỏ. Dùng `city + zone_name` + tâm GPS + bán kính đơn giản, match theo khoảng cách gần nhất |
| Vector DB | Qdrant, xem mục 1 |
| Taxi pricing động (Matrix API + hệ số mưa/giờ cao điểm) | Bỏ. Bảng giá cố định VND/km theo vùng |
| Dịch giọng nói 2 chiều real-time | Turn-based (bấm ghi âm → STT → dịch → TTS), chấp nhận độ trễ 3-5s |
| GDPR đầy đủ + auto-blur local | Regex redact số thẻ/CMND trước khi gửi lên LLM |
| STT trong lúc gọi khẩn cấp thật | Bỏ. Nút gọi = click-to-call xác định, không xử lý audio trong cuộc gọi |
| Module 2.2 đầy đủ (burst-review detection, Instagram, Facebook API chính thức) | Rút gọn mạnh — xem mục 5, phần lớn dồn sang Phase 2 |
| Login/tài khoản thật (auth, password) | Bỏ. Chỉ cần onboarding chọn ngôn ngữ + quốc tịch, tạo session id |

**Cảnh báo quan trọng:** module 2.2 (ghost tour/homestay) mới thêm vào làm khối lượng việc tăng đáng kể so với 3 tính năng ban đầu. Nếu team dưới 5 người, **không** làm đủ cả 2.2 trong 48h cùng lúc với 1, 2.1, 3 — xem roadmap mục 7 để biết phần nào cắt trước.

---

## 3. Kiến trúc agentic

**Nguyên tắc:** single orchestrator + tool-calling (function calling có sẵn của model), không multi-agent swarm.

**Tool expose cho agent:**

- `estimate_fair_price(item, region, observed_price)` — Qdrant kNN trên collection `item_names` để tìm item gần nhất (payload trỏ đến row Postgres), sau đó chạy Bayesian fusion (mục 6.1)
- `read_image(image, mode)` — 1 tool vision đa năng, `mode ∈ {receipt, dish, page_transparency, chat_screenshot}`. Gộp chung thay vì tách nhiều tool riêng cho hóa đơn/món ăn/ảnh chụp trang mạng xã hội/ảnh chụp tin nhắn — cùng là "đọc ảnh, trả text có cấu trúc", khác nhau ở prompt/schema output theo mode
- `match_scam_pattern(text, category)` — Qdrant kNN trên collection `scam_patterns`, filter theo `category ∈ {price_scam, ghost_tour_pressure}`
- `check_domain_age(url)` — WHOIS lookup, trả ngày đăng ký domain
- `check_business_existence(name, region)` — Google Places API, trả rating/review_count/recent_reviews
- `translate_or_get_hotline(text, region, nationality)` — dịch + tra hotline y tế/công an theo `region`, tra đại sứ quán theo `nationality` (không phải theo ngôn ngữ, xem mục 8)
- `trigger_sos()` — **không nằm trong quyền tự quyết của agent**, xem quy tắc an toàn dưới

**Critic pass:** mọi kết luận về giá bất thường hoặc scam risk (từ cả 2.1 lẫn 2.2) phải qua 1 lượt LLM thứ hai, chỉ hỏi "bằng chứng đủ mạnh không, có cách giải thích khác không" trước khi chốt — xử lý trực tiếp vấn đề false-alarm rate.

**Quy tắc an toàn cứng:** agent không bao giờ tự trigger gọi khẩn cấp. Nút SOS là đường tắt hardcoded, kích hoạt bằng người dùng bấm. Agent chỉ đề xuất ("có dấu hiệu rủi ro cao, bạn có muốn gọi hỗ trợ?"), không tự thực hiện.

**Memory:** transcript phiên truyền vào context, nén định kỳ — xem mục 4.

---

## 4. Module 1 — Dịch thuật

- Onboarding: chọn ngôn ngữ native **và quốc tịch riêng biệt** (không suy ra quốc tịch từ ngôn ngữ — khách nói tiếng Anh có thể từ Mỹ/Anh/Úc/Singapore, tiếng Trung có thể từ Trung Quốc/Đài Loan/Singapore). Quốc tịch cần cho routing đại sứ quán ở module 3.
- Ghi âm theo lượt (bấm nút), không nghe liên tục — phù hợp giới hạn latency turn-based đã chốt.
- STT dùng language hint từ ngôn ngữ đã chọn để tăng độ chính xác, vẫn bật auto-detect dự phòng vì hội thoại có thể xen tiếng Việt của người bản địa.
- **Tóm tắt hội thoại phải nén định kỳ**, không truyền toàn bộ transcript vô hạn vào context: sau mỗi ~10 lượt, gọi LLM tóm tắt các lượt cũ, giữ summary + N lượt gần nhất nguyên văn.
- **Cơ chế raise flag:** sau mỗi lượt ghi âm, transcript được gửi song song qua `match_scam_pattern` với cả 2 category (`price_scam`, `ghost_tour_pressure`), kết quả hiện ngay cạnh bản tóm tắt trên UI.

---

## 5. Module 2.1 — Price reasoning (bán lẻ/dịch vụ/di chuyển)

Giữ nguyên thiết kế Bayesian đã chốt trước đó, chuyển vector layer sang Qdrant:

- GPS khách hàng → tìm `zone_name` gần nhất trong Postgres (so khoảng cách tâm, không polygon) → dùng làm `region` cho các lookup.
- Upload ảnh hóa đơn/menu/bảng giá hoặc chụp món ăn → `read_image(mode=receipt|dish)` → trả tên món + giá (nếu có) + độ tin cậy nhận diện + gợi ý khẩu phần.
- So giá qua `estimate_fair_price` → **chỉ raise flag "cao hơn mức tham khảo X%, độ tin cậy Y%"**, không kết luận lừa đảo hay không — đúng tinh thần bản gốc.
- Xích lô/thuyền bè: giá cố định theo km/chuyến/vùng thay vì pricing động — bảng giá này cũng nạp vào Postgres như một `category` riêng trong `price_references`.

---

## 6. Chi tiết kỹ thuật cốt lõi (khác biệt thật, không chỉ gọi API)

### 6.1 Ước lượng giá công bằng bằng Bayesian fusion

Vấn đề: chỉ có vài chục điểm giá thật/địa điểm — trung bình cộng thô vô nghĩa về thống kê.

- Log-space: `y = ln(giá)`, giả định `y ~ N(μ, σ²)`.
- **Prior từ LLM:** hỏi Gemini Flash p10/p50/p90 + mức tự tin (thấp/tb/cao). `μ0 = ln(p50)`, `σ0 = (ln(p90) − ln(p10)) / (2×1.2816)`, nhân hệ số theo mức tự tin.
- **Cập nhật Bayes (Normal-Normal conjugate):**

  ```
  posterior_precision = 1/σ0² + n/σ_data²
  μ_post = (μ0/σ0² + n·ȳ/σ_data²) / posterior_precision
  τ_post² = 1/posterior_precision
  ```

- **Z-score có độ tin cậy:** `z = (ln(giá quan sát) − μ_post) / sqrt(τ_post² + σ_data²)` → percentile, kèm "độ tin cậy dựa trên n điểm dữ liệu".
- **Update online:** mỗi điểm dữ liệu mới → `UPDATE price_references SET mu_post=..., tau_post=..., n=n+1` trong Postgres, O(1), không đụng Qdrant.
- **Lookup tên món qua Qdrant:** tên món OCR/VLM trả về hiếm khi khớp chuỗi chính xác ("Phở Bò" vs "pho bo tai đặc biệt"). Embed tên món, kNN trên collection `item_names` (payload lọc theo `region`), lấy id Postgres của điểm gần nhất. Similarity cao nhất < 0.55 → coi là item chưa có dữ liệu, chỉ dùng prior LLM (n=0).

### 6.2 Phát hiện scam pattern MỚI (stretch goal)

- Embed report, kNN trên collection `scam_patterns` (Qdrant). Similarity < 0.6 → ghi vào collection riêng `unmatched_reports` (payload: transcript, region, category_guess, created_at) thay vì bảng Postgres — Qdrant là nguồn duy nhất cho mọi thứ liên quan vector.
- Định kỳ: scroll collection `unmatched_reports`, kéo vector về client, chạy clustering (DBSCAN/agglomerative bằng scipy — Qdrant không tự cluster, chỉ lưu trữ + kNN). Cụm ≥3 report tương đồng, xa mọi pattern đã biết → gắn cờ "candidate pattern mới", admin duyệt để thêm point mới vào `scam_patterns`.
- Demo bằng dữ liệu tiêm giả, rehearse trước, không tune threshold live.
- Ưu tiên thấp hơn 6.1 — chỉ làm nếu dư giờ.

### 6.3 PII redaction

Regex pass che số thẻ/CMND trên text OCR trước khi gửi tiếp lên LLM. Dưới 1 giờ code.

### 6.4 Lớp VLM nhận diện món ăn + định giá

- `read_image(mode=dish)` trả:

  ```json
  {
    "detected_price_text": "35000 VND" | null,
    "dish_candidates": [{"name": "Phở bò tái", "confidence": 0.82}],
    "portion_cues": "tô vừa, thịt vừa phải" | "tô lớn nhiều topping" | "không rõ"
  }
  ```

- Có giá → verify mode. Không có → quote mode qua `estimate_fair_price(observed_price=None)`.
- Độ tin cậy VLM truyền vào phương sai prior: `σ0 × (1 + (1 − confidence))`, nhân thêm ×1.5 nếu `portion_cues = "không rõ"`.
- Giới hạn scope: chỉ curate 15-20 món đặc trưng/địa điểm, ngoài danh sách thì trả lời "không đủ tự tin nhận diện" thay vì đoán bừa.
- Output luôn kèm caveat, không khẳng định.

---

## 7. Module 2.2 — Ghost tour & homestay detector

Đây là phần yếu nhất trong bản gốc về mặt khả thi dữ liệu — cần nói rõ với team cái gì làm được thật trong 48h và cái gì không.

**Rào cản thật cần biết trước khi build:**

- Facebook Graph API **không** cho bên thứ ba xem ngày tạo trang, lịch sử đổi tên, hay danh sách review đầy đủ của một page bất kỳ (khóa chặt từ sau vụ Cambridge Analytica). Viết scraper để lấy các dữ liệu này vi phạm ToS và dễ vỡ (chặn IP, tường đăng nhập) — không nên cam kết pipeline tự động ổn định trong 48h.
- Instagram còn hạn chế hơn — gần như không lấy được comment/review công khai của page lạ qua API chính thức. **Bỏ Instagram khỏi phạm vi kỹ thuật thật.**
- Google Places API cho rating + review_count + tối đa 5 review gần nhất, nhưng **không** cho lịch sử timestamp đầy đủ để phát hiện "review dồn cùng lúc" (burst detection) — tín hiệu này không khả thi đầy đủ trong 48h với data access hiện có.

**Giải pháp thực tế (tái dùng hạ tầng đã có thay vì scraping mới):**

1. **Tuổi domain (website):** `check_domain_age(url)` qua WHOIS — tín hiệu rẻ, hợp pháp, mạnh. Domain đăng ký <6 tháng → risk cao.
2. **Tuổi/lịch sử page (Facebook):** thay vì scraper, dùng lại tool `read_image(mode=page_transparency)` — yêu cầu người dùng chụp màn hình mục "Page Transparency" (công khai, ai cũng xem được trong app Facebook), VLM đọc ngày tạo + lịch sử đổi tên. Biến bài toán scraping khó thành bài toán đọc ảnh đã có sẵn hạ tầng từ module 2.1.
3. **Tồn tại/uy tín cơ bản:** `check_business_existence(name, region)` qua Google Places — chỉ dùng để check review_count > ngưỡng tối thiểu và xem 5 review gần nhất có bất thường không (tín hiệu yếu nhưng miễn phí và hợp pháp).
4. **Giá thấp bất thường:** tái dùng `estimate_fair_price` — z-score **rất âm** → raise flag "giá thấp bất thường so với mặt bằng, cẩn trọng mồi câu giá rẻ" (ngược hướng với 2.1 nhưng cùng 1 tool).
5. **Ngôn ngữ thúc giục / phụ phí ẩn:** tái dùng `match_scam_pattern(text, category="ghost_tour_pressure")`, seed 15-20 câu mẫu ("giảm 70% chỉ hôm nay", "chuyển khoản cọc 100% giữ chỗ", "còn 2 phòng cuối"...). Input là text cào từ website, hoặc `read_image(mode=chat_screenshot)` nếu khách chụp màn hình tin nhắn/DM nghi vấn — né được việc cần API Messenger/Zalo.
6. **Composite trust score:** tổng hợp có trọng số 4-5 tín hiệu trên, hiển thị breakdown từng mục cho khách xem, không chỉ 1 số duy nhất — giữ đúng triết lý minh bạch đã thống nhất ở các module khác.

**Cắt giảm bắt buộc nếu team <5 người:** chỉ làm (1) tuổi domain WHOIS + (4) giá thấp bất thường cho MVP — đây là 2 tín hiệu rẻ nhất, tái dùng nhiều nhất. (2), (3), (5) đánh dấu Phase 2 trong pitch, demo bằng 1 kịch bản đã chuẩn bị sẵn (không tổng quát hóa live).

---

## 8. Module 3 — Emergency

- Routing đại sứ quán theo **quốc tịch** (bảng `embassies` trong Postgres, khóa theo nationality), routing công an/y tế theo **region** (GPS). Không dùng ngôn ngữ để suy ra quốc tịch — xem lý do ở mục 4.
- **STT trong lúc gọi thật là bài toán khó nhất về mặt telephony** (cần Twilio Media Streams + STT streaming real-time) — không khả thi build chắc trong 48h. MVP: nút gọi = click-to-call xác định (`tel:` link, hoặc Twilio Voice nếu muốn polish demo trong app), không xử lý audio trong cuộc gọi. Đánh dấu rõ ràng đây là Phase 2 trong pitch, không hứa live.
- **Trigger gợi ý:** khi module 2 (2.1 hoặc 2.2) trả composite risk vượt ngưỡng, UI hiển thị gợi ý "Có dấu hiệu rủi ro cao, bạn có muốn gọi hỗ trợ khẩn cấp?" cạnh transcript — hành động gọi luôn cần người dùng bấm tay, agent không tự dial (quy tắc an toàn cứng ở mục 3).

---

## 9. Roadmap 48 giờ (đã tính cả module 2.2)

| Khung giờ | Việc chính |
|---|---|
| 0-6h | Setup FastAPI, Qdrant (Docker/cloud), Postgres (Supabase); tạo collections/tables; nhập tay dữ liệu giá 3 địa điểm + seed 30 scam pattern (`price_scam`) + 15-20 pattern (`ghost_tour_pressure`) |
| 6-16h | Module 1 (dịch turn-based) + Module 2.1 (quét hóa đơn/món ăn, Bayesian) — ưu tiên tuyệt đối, làm chắc trước |
| 16-26h | Module 2 scam voice matching (Qdrant) tích hợp vào flag của Module 1 |
| 26-34h | Module 3 emergency tĩnh (hotline theo vùng + đại sứ quán theo quốc tịch, click-to-call) |
| 34-42h | Module 2.2 bản rút gọn: chỉ WHOIS domain age + price-floor reuse (mục 7, cắt giảm bắt buộc) |
| 42-46h | Tích hợp, test end-to-end 3-4 kịch bản demo |
| 46-48h | Quay demo, viết pitch nêu rõ Phase 2: STT-trong-cuộc-gọi, burst-review detection, Page Transparency qua VLM, Instagram |

---

## 10. Việc cần team tự quyết

- Roadmap giả định 4-5 người chia song song các module. Nếu team nhỏ hơn: bỏ hẳn module 2.2 khỏi MVP, dồn lực làm chắc module 1 + 2.1 + 3, demo ghost-tour detector bằng slide/mockup thay vì code chạy thật.
- Xác nhận: embedding cho Qdrant tạo bằng model nào (local sentence-transformer hay API) — ảnh hưởng chi phí và latency lúc index dữ liệu ban đầu.
- Xác nhận: Twilio (hoặc dịch vụ click-to-call tương đương) có tài khoản sẵn không, hay chỉ dùng `tel:` link đơn giản cho demo.
