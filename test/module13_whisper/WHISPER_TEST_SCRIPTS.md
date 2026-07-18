# Whisper Test Scripts

Use one recording per script. Read the text exactly as written, without reading
the ID or scenario label. Keep each clip between 3 and 10 seconds. Save files
with the matching names under `test/module13_whisper/audio/`.

The text in the `Expected transcript` column is the reference transcript for
WER and entity checks. Minor punctuation differences should not count as a
failure.

| ID | File | Scenario | Expected transcript |
|---|---|---|---|
| W001 | `w001_price_question.wav` | Clear vendor conversation | `Cho tôi hỏi bát phở này giá bao nhiêu?` |
| W002 | `w002_price_scam.wav` | Price and distance | `Tài xế muốn lấy tám trăm nghìn cho quãng đường hai cây số.` |
| W003 | `w003_local_place.wav` | Vietnamese place names | `Tôi muốn đi từ phố cổ Hà Nội đến hồ Hoàn Kiếm.` |
| W004 | `w004_mixed_language.wav` | Vietnamese and English code-switching | `Is this price for one person hay cho cả nhóm?` |
| W005 | `w005_payment_pressure.wav` | Payment pressure signal | `Họ bảo tôi phải chuyển khoản ngay hôm nay, nếu không sẽ mất tiền cọc.` |
| W006 | `w006_sos_request.wav` | Immediate safety request | `Xin hãy gọi cảnh sát, tôi đang bị giữ lại và không được rời đi.` |
| W007 | `w007_embassy.wav` | Embassy and nationality | `Đại sứ quán Hoa Kỳ ở Hà Nội cách đây bao xa?` |
| W008 | `w008_numbers.wav` | Numbers and phone number | `Số điện thoại của tôi là không chín không ba, một hai ba, bốn năm sáu.` |
| W009 | `w009_vendor_fast.wav` | Fast vendor speech | `Bún chả này một trăm hai mươi nghìn, đã bao gồm nước và rau rồi.` |
| W010 | `w010_multi_entity.wav` | Mixed entities and location | `Ngày mai tôi đi Sa Pa, cần đặt xe từ Hà Nội lúc sáu giờ sáng.` |

## Recording Variants

Record W001-W005 and W007-W010 in a quiet place. Record W006 once clearly and
once with mild background noise. For a second quality pass, record W002, W005,
and W009 at a natural conversational speed instead of reading slowly.

Normalize each file to mono, 16 kHz, 16-bit PCM WAV before benchmarking:

```powershell
ffmpeg -i input.webm -ar 16000 -ac 1 -sample_fmt s16 output.wav
```

Suggested manifest columns:

```csv
id,file,language,transcript,scenario
W001,audio/w001_price_question.wav,vi,"Cho tôi hỏi bát phở này giá bao nhiêu?",price
W002,audio/w002_price_scam.wav,vi,"Tài xế muốn lấy tám trăm nghìn cho quãng đường hai cây số.",price_scam
```
