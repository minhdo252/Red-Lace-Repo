# AITravelMate — `/chat` Orchestration Flow

Deterministic pre/post pipeline wraps a bounded agentic tool loop. Only 3 tools are exposed to the LLM — `check_ghost_tour`'s 6 signals run internally/in parallel rather than as separate LLM-chosen tool calls, keeping tool-choice cheap. SOS is fully outside the agentic loop and only ever user-initiated.

```mermaid
flowchart TD
    A["User message /chat<br/>text, audio, or image"] --> B{"STT required?<br/>request.audio_base64"}
    B -- yes --> C["Transcribe<br/>FPT Whisper-large-v3-turbo"]
    B -- no --> D
    C --> D["clean_text<br/>(PII redacted)"]
    
    D --> E["asyncio.gather<br/>Parallel Execution"]
    
    E -->|1| F["Translate — Module 1<br/>deterministic Chat LLM call"]
    E -->|2| G["Scam prefilter<br/>Qdrant + Rule Fallback"]
    E -->|3| H["Threat detection<br/>Cumulative session risk"]
    E -->|4| I["Orchestrator<br/>handle_turn"]

    subgraph ORCH["Orchestrator loop — up to 5 iterations"]
        I --> J["Upfront VLM parse (if image)<br/>Qwen2.5-VL-7B, injected into context"]
        J --> K["LLM Tool Loop<br/>Llama-3.3-70B-Instruct"]
        K --> L["estimate_fair_price<br/>Qdrant kNN, gate 0.75 + prefix"]
        K --> M["match_scam_pattern<br/>Qdrant kNN vs scam_patterns"]
        K --> N["check_ghost_tour<br/>6 signals, parallel"]
        L -- below gate --> L2["Web fallback<br/>gemini-3.1-flash-lite, search-grounded<br/>writes back to Postgres + Qdrant"]
        L2 --> K
        M --> K
        N --> K
        K -- "loop exits: done or 5 iters" --> O{"Risk flagged?<br/>from estimate_fair_price / check_ghost_tour"}
        O -- yes --> P["Critic pass<br/>2nd LLM call, confirms explicit warning"]
        O -- no --> Q["turn_result"]
        P --> Q
    end

    F --> R["Compose response<br/>translation + risk badges + sos_flag"]
    G --> R
    H --> R
    Q --> R

    H -- CRITICAL --> S["sos_flag = true<br/>no autonomous dial"]
    S --> R
    R --> T["Return to chatbot / frontend"]

    subgraph SOS["Separate, user-initiated"]
        U["POST /sos<br/>user taps SOS modal"] --> V["Resolve GPS<br/>else 45km radius fallback"]
        V --> W["Prioritized hotlines + embassies"]
    end
```

**Legend**
- Solid arrow = always executes. Dashed/labeled branch = conditional.
- `ORCH` subgraph = the only part of `/chat` where the LLM chooses actions; everything outside it is a fixed deterministic pipeline.
- `SOS` subgraph = never reachable from inside `/chat` or the tool loop — matches the hard rule that the agent cannot autonomously trigger SOS.