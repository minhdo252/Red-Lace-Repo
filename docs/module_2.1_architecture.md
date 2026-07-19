# Module 2.1: Price Comparison & Receipt/Dish Analysis

Module 2.1 is responsible for analyzing tourist receipts or food images, identifying the items, and comparing their prices against local baselines to flag potential price gouging.

## Tech Stack
- **Vector Database**: **Qdrant** (`item_names` collection) for k-Nearest Neighbors (kNN) similarity search.
- **Relational Database**: **PostgreSQL** (`price_references` table) for storing structured pricing data.
- **AI / LLMs**:
  - **Vision Model**: `Qwen2.5-VL-7B-Instruct` (via FPT AI Marketplace) for parsing receipts and dish photos.
  - **Embedding Model**: `Vietnamese_Embedding` (via FPT AI Marketplace) for converting Vietnamese dish names into 1024-dimensional vectors.
  - **Search Model**: `gemini-3.1-flash-lite` (via `google-genai` SDK) for live web search and dynamic price extraction.
- **Frameworks**: `FastAPI` (routing), `asyncio` (non-blocking thread execution), `tenacity` (retry logic).

---

## 1. Image Reading & Parsing (`image_reader.py`)
When a user uploads a photo of a receipt or a dish, the orchestrator routes it to `read_image()` before initiating the tool-calling loop.
- The image is converted to Base64 and sent to the **Qwen2.5-VL-7B-Instruct** vision model.
- The model extracts structured JSON identifying:
  - `detected_price_text`: The price written on the receipt/menu.
  - `dish_candidates`: What the dish likely is based on visual cues.
  - `portion_cues`: Size indicators (e.g., "1 bát", "1 lít").
- These insights are injected directly into the Orchestrator's prompt context as immutable facts.

## 2. Local kNN Price Comparison (`price_comparison.py`)
When the orchestrator triggers the `estimate_fair_price` tool, the system attempts a local cache lookup first for maximum speed.
1. **Vectorization**: The queried dish name is embedded using `Vietnamese_Embedding` (offloaded to `asyncio.to_thread` with a 5.0s timeout to prevent event loop blocking).
2. **Qdrant Lookup**: A kNN query fetches the top 10 neighbors in the same `region` (e.g., Hanoi) and `category` (e.g., food).
3. **Two-Stage Gating**:
   - **Similarity Gate**: Discards neighbors with a cosine similarity below `0.75`.
   - **Head-Phrase Gate**: Extracts the linguistic "head" of the dish (e.g., "bún chả" from "bún chả đặc biệt") and requires a prefix match. This prevents "pizza hải sản" from matching "cơm trộn hải sản" simply because they share a modifier.
4. **Aggregation**: The surviving comparable neighbors (up to 3) are fetched from Postgres, and their prices are aggregated into a **similarity-weighted mean** to form the reference price.
5. **Markup Flagging**: If the user's `observed_price` is >30% higher than the local reference price, the system flags it as anomalous.

## 3. Dynamic Web Fallback (`price_web_fallback.py` & `gemini_search.py`)
If Qdrant fails, times out, or returns zero valid comparable neighbors, the pipeline gracefully routes to a web search fallback.
1. **Live Search**: Invokes `gemini-3.1-flash-lite` with the Google Search tool enabled.
2. **Strict Constraints**: 
   - Uses strict prompt engineering rules: `EXACT MATCHING` (rejects luxury/seafood substitutions for basic dishes), `PORTION SIZE` (rejects 1-liter pitchers or family combos when querying street drinks), and `AMBIGUOUS ITEMS` (returns `no-match` for overly generic queries like "cơm").
3. **Data Caching**: If Gemini successfully finds a fair price online, it returns it instantly to the user to keep latency low.
4. **Background Persistence**: In the background, the new item is embedded and saved into both Postgres and Qdrant. The *next* time a tourist asks about this dish, it will resolve locally in < 0.3s instead of triggering a web search.

---

## 4. Input & Output Shapes

### Image Parsing (`read_image`)
- **Input**: `image_bytes` (Base64 decoded) and `mode` (e.g., `"receipt"` or `"dish"`).
- **Output**: 
  ```json
  {
    "detected_price_text": "35,000", 
    "dish_candidates": ["phở bò", "bún bò"], 
    "portion_cues": "1 bát"
  }
  ```

### Price Comparison (`estimate_fair_price`)
- **Input**: 
  ```json
  {
    "item": "phở bò",
    "region": "Hanoi",
    "category": "food",
    "observed_price": 80000
  }
  ```
- **Output**:
  ```json
  {
    "item": "phở bò",
    "matched": true,
    "reference_source": "local",
    "reference_price": 50000,
    "price_diff_pct": 60.0,
    "flag": "cao hơn giá tham chiếu 60% — trung bình có trọng số 3 món gần nhất giá 50,000 VND"
  }
  ```

---

## 5. Agent, Orchestrator, & Critic Integration

### Orchestrator Integration
Module 2.1 integrates with the single-agent orchestrator loop in two distinct phases:
1. **Pre-processing (Images)**: The model is not asked to call an image-reading tool. Since an LLM cannot magically request image bytes it hasn't seen yet, the orchestrator's `_read_images()` function evaluates all `ImagePayload` attachments upfront. The resulting JSON is injected directly into the LLM's context as `system` notes before the agent begins reasoning.
2. **Tool Calling (Prices)**: Once reasoning begins, the agent can invoke the `estimate_fair_price` tool defined in `TOOL_SPECS`. It extracts the dish name (either from user chat or from the pre-processed image `dish_candidates`) and queries the price comparison pipeline.

### Critic Integration
The orchestrator delegates safety and risk verification to an asynchronous `critic_pass`.
1. **Risk Flagging**: `estimate_fair_price` is registered as a `RISK_TOOL` in `orchestrator.py`. If the price pipeline outputs a truthy `flag` (triggered when the markup exceeds 30%), the orchestrator flips `risk_flag_raised = True`.
2. **Critic Review**: Before returning the response to the user, the orchestrator sends its own draft `reply` alongside the `tools_invoked` data to the Critic.
3. **Safety Gate**: The Critic evaluates whether the agent properly warned the user about the price gouging. If the agent's tone is too casual or fails to mention the anomaly, the Critic can rewrite the response to prioritize the tourist's safety.
