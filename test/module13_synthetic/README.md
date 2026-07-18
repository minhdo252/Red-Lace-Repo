# Module 1 and 3 Synthetic Test Pack

This directory contains synthetic fixtures for backend Module 1 and Module 3.
It intentionally avoids crawler, pricing-reference, image, and unrelated routes.

## Coverage

- transcript formatting and grouped-number normalization
- deterministic numeric/word-form VND normalization and false-positive guards
- PII redaction
- deterministic scam fallback rules
- Qdrant scam-vector matching with temporary fixture points
- threat keyword scan and false-alarm context
- `/sessions` and `/chat` response contracts
- live GLM translation/scam/threat quality subset
- ten recorded Whisper cases and WER thresholds
- SOS routing for Hanoi, Sapa, Hoi An, and national fallback
- embassy inclusion, primary contact ordering, idempotency, and rate limiting
- HTTP validation for malformed input and missing sessions
- GLM structured-output compatibility and background-task failure isolation

The runner creates normal application sessions and events with fixture-prefixed
idempotency keys. Qdrant points use the exact IDs from `dataset.json` and are
removed in a `finally` block after each suite.

Run from the repository root:

```powershell
$env:PYTHONPATH = "$PWD\backend"
python test\module13_synthetic\run_dataset.py --suite contract
python test\module13_synthetic\run_dataset.py --suite live
python test\module13_synthetic\run_dataset.py --suite audio
```

`contract` switches the shared AI client to mock mode while exercising the real
FastAPI routes, Postgres, and Qdrant. `live` uses configured model keys for the
four quality cases. `audio` runs all ten WAV fixtures through the full `/chat`
pipeline and evaluates WER.

The latest completed run is recorded in [RESULTS.md](RESULTS.md). The live and
audio suites return a non-zero exit code for any failed quality assertion, while
still attempting the remaining cases and Qdrant cleanup.
