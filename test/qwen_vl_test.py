"""
qwen_vl_test.py
---------------
Quick manual smoke test for app/ai/qwen_vl.py::ai_detect_menu — runs it
against the sample handwritten menu photo at test/menu 1.jpg and prints
whatever comes back (parsed rows, or the raw response if parsing failed).

Needs QWEN_VL_API_KEY set in the environment (see .env.example).

Run via Docker (same PYTHONPATH=/app convention as the other test/ scripts):
    docker compose run --rm -e QWEN_VL_API_KEY=... backend \\
        python test/qwen_vl_test.py

Run locally (from repo root, with backend/requirements.txt installed):
    cd backend && PYTHONPATH=. QWEN_VL_API_KEY=... python ../test/qwen_vl_test.py
"""

from pathlib import Path

from app.ai.qwen_vl import ai_detect_menu

IMAGE_PATH = Path(__file__).parent / "menu 1.jpg"
REGION = "Hanoi/Old Quarter"  # photo's actual location — required, see ai_detect_menu docstring


def main() -> None:
    result = ai_detect_menu(str(IMAGE_PATH), region=REGION)

    print("\n\n--- Result ---")
    if result.parse_error:
        print(f"PARSE ERROR: {result.parse_error}")
        print("Raw response:", result.raw_response)
        return

    print(f"Ready rows ({len(result.ready_rows)}):")
    for row in result.ready_rows:
        print(f"  {row.item_name} - {row.price_vnd} VND")

    print(f"\nNeeds review ({len(result.needs_review)}):")
    for item in result.needs_review:
        print(f"  {item.name_raw} - {item.price_raw} (uncertain={item.uncertain}, notes={item.notes!r})")

    print(f"\nUnreadable regions skipped: {result.unreadable_regions}")


if __name__ == "__main__":
    main()
