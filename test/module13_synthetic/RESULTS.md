# Module 1 and 3 Synthetic Test Results

Ngay chay: 2026-07-18  
Base commit cua working tree: `636650c`  
Pham vi: backend Module 1 va Module 3; khong test crawler, pricing-reference, image hoac vision.

## Tong ket

| Suite | Passed | Failed | Thoi gian |
|---|---:|---:|---:|
| Contract + Postgres + Qdrant | 261 | 0 | 0.762 s |
| Live text: GLM-5.2 + Vietnamese_Embedding | 51 | 0 | 168.201 s |
| Full audio: whisper-large-v3-turbo | 125 | 0 | 327.647 s |
| **Tong** | **437** | **0** | **496.610 s** |

Tat ca fixture Qdrant co ID co dinh da duoc xoa. Kiem tra doc lap sau test tra ve
`remaining_fixture_points=[]`.

## Module 1

Da pass cac nhom sau:

- session normalization, session-not-found va input validation
- text/audio `/chat`, response contract, persistence va chunk idempotency
- GLM-5.2 structured output trong `reasoning_content`
- detected language va target language
- grouped-number, `k`, VND, so chu tieng Viet va gia ghep trieu-nghin
- chan false positive cho phone, OTP, ma xac nhan va khoang cach
- PII redaction
- scam rule fallback va Qdrant vector source
- background history compression khong lam hong request khi AI provider loi
- 10/10 WAV di qua full pipeline

Live text:

| Case | Latency | Ket qua chinh |
|---|---:|---|
| L001 | 29.712 s | `en`, `[800000]`, `price_scam`, threat `NONE` |
| L002 | 12.587 s | `en`, `ghost_tour_pressure`, threat `NONE` |
| L003 | 60.718 s | `en`, threat `CRITICAL` |
| L004 | 3.247 s | `en`, benign, threat `NONE` |

## Module 3

Da pass cac nhom sau:

- Tier-1 threat keyword scan cho CRITICAL/HIGH/NONE
- false-alarm downgrade cho movie/past context va souvenir knife
- cumulative threat state persistence
- manual SOS va smart-trigger SOS
- routing theo `physical_violence`, `medical_emergency`, `financial_coercion`,
  `sophisticated_scam`, `robbery_theft`, `unlawful_detention` va universal distress
- Hanoi, Sapa, Hoi An va national fallback
- police/medical/tourist-police primary ordering
- embassy theo nationality va truong hop khong co embassy
- exactly-one-primary, stable priority rank, event persistence
- SOS idempotency, rate limiting va malformed-input validation

## Audio Benchmark

Mean WER: **0.2770**, acceptance threshold: `<= 0.35`.

| Case | WER | Max WER | Latency | Ket qua nghiep vu |
|---|---:|---:|---:|---|
| W001 | 0.0000 | 0.10 | 12.599 s | benign |
| W002 | 0.4615 | 0.60 | 61.613 s | `[800000]`, `price_scam` |
| W003 | 0.0000 | 0.10 | 16.218 s | place names dung |
| W004 | 0.7000 | 0.75 | 24.359 s | benign; STT lam mat phan code-switch |
| W005 | 0.1333 | 0.20 | 19.074 s | `ghost_tour_pressure` du STT sai mot tu |
| W006 | 0.0667 | 0.10 | 7.437 s | threat `CRITICAL` |
| W007 | 0.0000 | 0.10 | 8.141 s | embassy/place names dung |
| W008 | 0.6250 | 0.70 | 11.874 s | phone transcript du thong tin |
| W009 | 0.5333 | 0.60 | 33.724 s | `[120000]` |
| W010 | 0.2500 | 0.30 | 131.049 s | multi-entity benign |

W002 audio replay tra ve dung nguyen response da persist, xac nhan chunk idempotency.

## Loi Phat Hien Va Da Sua

1. GLM-5.2 tra structured JSON trong `reasoning_content` khi `content=null`.
   Gateway gio chi dung fallback nay cho structured requests; normal chat van uu tien
   final `content` de khong lo reasoning noi bo.
2. GLM co the tra `key_entities` va `normalized_prices_vnd` duoi dang object.
   Translation layer gio coerce schema, parse JSON fence/prefix va merge voi parser gia
   deterministic.
3. Gia nhu `800.000`, `800k`, `tam tram nghin`, `mot trieu hai tram nghin` va bare
   VND amount co ngu canh duoc chuan hoa; phone/OTP/code/km khong bi xem la gia.
4. Transcript W005 co the bi Whisper nghe `chuyen khoan` thanh `chuyen khuan`.
   Rule pressure van bat duoc cap tin hieu `ngay hom nay` + `mat tien coc`.
5. Loi provider trong history compression tung propagate tu background task.
   Task gio bat va log exception, khong lam hong request.
6. Runner gio tiep tuc cac audio con lai neu mot provider request nem exception va van
   cleanup chinh xac fixture Qdrant.

## Rui Ro Con Lai

- Correctness dat acceptance hien tai, nhung latency live co tail lon: L003 `60.718 s`
  va W010 `131.049 s`. Can benchmark concurrency/load rieng truoc production.
- W004, W008 va W009 pass threshold nhung WER con cao. Can them audio nhieu giong noi,
  tieng on va thiet bi that truoc khi coi STT quality la production-grade.
- Mot luot dau gap loi TLS tam thoi tu provider; luot cuoi pass. Day van la rui ro external
  dependency, khong nen tat SSL verification.
- Host Windows canh bao chua co ffmpeg. Bo WAV nay van pass; Docker image da cai ffmpeg
  cho input M4A/WebM production.
- Qdrant local dung API key qua HTTP nen client canh bao insecure connection. Production
  can HTTPS/TLS.

## Chay Lai

Tu repository root:

```powershell
python test\module13_synthetic\run_dataset.py --suite contract
python test\module13_synthetic\run_dataset.py --suite live
python test\module13_synthetic\run_dataset.py --suite audio
```

`contract` dung mock AI nhung FastAPI, Postgres va Qdrant la that. `live` va `audio`
dung model/key trong `.env`; runner khong in API key ra output.
