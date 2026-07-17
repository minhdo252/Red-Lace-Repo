"""Three-layer threat detection for emergency smart triggers."""

from __future__ import annotations

import json
import re
import uuid
from collections import defaultdict
from dataclasses import asdict, dataclass, field

from app.ai.client import ai_client
from app.db.postgres import get_pool


@dataclass
class ThreatPattern:
    category: str
    default_level: str
    keywords: list[str] = field(default_factory=list)
    phrases: list[str] = field(default_factory=list)


THREAT_PATTERNS: list[ThreatPattern] = [
    ThreatPattern(
        category="robbery_theft",
        default_level="CRITICAL",
        keywords=[
            "cướp",
            "giật",
            "trộm",
            "móc túi",
            "robbed",
            "robbery",
            "mugged",
            "stolen",
            "pickpocket",
            "snatched",
            "강도",
            "소매치기",
            "抢劫",
            "小偷",
            "ひったくり",
        ],
        phrases=[
            "bị giật túi",
            "mất ví",
            "mất điện thoại",
            "stole my",
            "took my bag",
            "grabbed my phone",
            "my wallet is gone",
            "被抢了",
        ],
    ),
    ThreatPattern(
        category="physical_violence",
        default_level="CRITICAL",
        keywords=[
            "đấm",
            "đạp",
            "đâm",
            "chém",
            "dao",
            "kim tiêm",
            "bóp cổ",
            "hit me",
            "punch",
            "stabbed",
            "knife",
            "attack",
            "assault",
            "weapon",
            "폭행",
            "칼",
            "打人",
            "刀",
            "暴力",
            "ナイフ",
        ],
        phrases=[
            "nó đánh tôi",
            "bị đánh rồi",
            "nó rút dao",
            "dọa giết",
            "he hit me",
            "they attacked",
            "pulled a knife",
            "someone is hurting",
            "有人攻击我",
        ],
    ),
    ThreatPattern(
        category="unlawful_detention",
        default_level="CRITICAL",
        keywords=[
            "giữ hộ chiếu",
            "giữ passport",
            "khóa cửa",
            "nhốt",
            "giam",
            "passport",
            "locked",
            "trapped",
            "detained",
            "hostage",
            "여권",
            "감금",
            "护照",
            "锁门",
            "被困",
        ],
        phrases=[
            "không cho tôi đi",
            "bắt tôi ở lại",
            "không trả passport",
            "won't let me leave",
            "can't get out",
            "took my passport",
            "locked the door",
            "不让我走",
        ],
    ),
    ThreatPattern(
        category="medical_emergency",
        default_level="CRITICAL",
        keywords=[
            "cấp cứu",
            "tai nạn",
            "chảy máu",
            "gãy",
            "bỏng",
            "ngất",
            "co giật",
            "dị ứng",
            "khó thở",
            "rắn cắn",
            "ambulance",
            "emergency",
            "accident",
            "bleeding",
            "unconscious",
            "seizure",
            "allergic",
            "injured",
            "구급차",
            "응급",
            "救护车",
            "急救",
            "救急車",
        ],
        phrases=[
            "cần cấp cứu",
            "không thở được",
            "bị tai nạn",
            "need an ambulance",
            "call an ambulance",
            "can't breathe",
            "badly injured",
            "需要急救",
        ],
    ),
    ThreatPattern(
        category="harassment_sexual",
        default_level="HIGH",
        keywords=[
            "sờ soạng",
            "quấy rối",
            "bám theo",
            "theo dõi",
            "sàm sỡ",
            "groping",
            "harassing",
            "following",
            "stalking",
            "touching",
            "성추행",
            "스토킹",
            "骚扰",
            "跟踪",
        ],
        phrases=[
            "nó sờ tôi",
            "bị sàm sỡ",
            "theo tôi hoài",
            "someone is following me",
            "touched me",
            "being followed",
            "有人跟踪我",
        ],
    ),
    ThreatPattern(
        category="financial_coercion",
        default_level="HIGH",
        keywords=[
            "tống tiền",
            "ép trả",
            "đe dọa",
            "bắt đền",
            "giữ đồ",
            "extortion",
            "blackmail",
            "forced to pay",
            "threatening",
            "pay or else",
            "勒索",
            "威胁",
        ],
        phrases=[
            "không trả tiền thì không được đi",
            "trả gấp mười lần",
            "giữ xe không cho đi",
            "won't let me go until I pay",
            "forcing me to pay",
            "pay ten times",
            "不付钱不让走",
        ],
    ),
    ThreatPattern(
        category="sophisticated_scam",
        default_level="HIGH",
        keywords=[
            "ngõ vắng",
            "đường vắng",
            "chỗ lạ",
            "dark alley",
            "wrong direction",
            "different route",
            "sketchy",
            "suspicious place",
            "수상한 곳",
            "偏僻",
        ],
        phrases=[
            "nó chở tôi đi chỗ khác",
            "không phải đường này",
            "driver is going the wrong way",
            "not the route on the map",
            "where is he taking me",
            "this doesn't look right",
            "司机走错路了",
        ],
    ),
    ThreatPattern(
        category="isolation_disorientation",
        default_level="HIGH",
        keywords=[
            "lạc đường",
            "bỏ rơi",
            "mất phương hướng",
            "lost",
            "stranded",
            "abandoned",
            "no signal",
            "alone",
            "길을 잃었",
            "迷路",
            "被丢下",
        ],
        phrases=[
            "không biết đang ở đâu",
            "tài xế bỏ tôi ở đây",
            "bị bỏ giữa đường",
            "driver left me here",
            "don't know where I am",
            "I'm stranded",
            "司机把我丢在这里",
        ],
    ),
]


UNIVERSAL_DISTRESS_SIGNALS = [
    "help me",
    "please help",
    "call the police",
    "call police",
    "call 113",
    "call 115",
    "save me",
    "i'm in danger",
    "emergency",
    "cứu tôi",
    "cứu với",
    "gọi công an",
    "gọi cảnh sát",
    "gọi 113",
    "gọi 115",
    "gọi cấp cứu",
    "nguy hiểm",
    "살려주세요",
    "도와주세요",
    "救命",
    "救我",
    "报警",
    "助けて",
]


@dataclass
class ThreatScanResult:
    has_threat: bool = False
    max_level: str = "NONE"
    matched_categories: list[dict] = field(default_factory=list)
    is_universal_distress: bool = False


@dataclass
class ThreatDetectionResult:
    final_level: str
    threat_categories: list[str]
    assessment: str
    reasoning: str
    show_sos_button: bool
    auto_open_sos_modal: bool
    primary_threat_category: str | None = None
    confidence: float = 0.0
    recommended_action: str = "Continue normal assistance"
    sos_reason: str | None = None
    cumulative_score: float = 0.0

    def to_dict(self) -> dict:
        return asdict(self)


def _contains_keyword(text_lower: str, keyword: str) -> bool:
    keyword_lower = keyword.lower()
    if any(ord(ch) > 127 for ch in keyword_lower):
        return keyword_lower in text_lower
    return re.search(r"(?<!\w)" + re.escape(keyword_lower) + r"(?!\w)", text_lower) is not None


def scan_threat_keywords(text: str) -> ThreatScanResult:
    text_lower = text.lower().strip()
    result = ThreatScanResult()

    for signal in UNIVERSAL_DISTRESS_SIGNALS:
        if signal.lower() in text_lower:
            result.has_threat = True
            result.max_level = "CRITICAL"
            result.is_universal_distress = True
            result.matched_categories.append(
                {"category": "universal_distress", "level": "CRITICAL", "matched_text": signal}
            )
            return result

    for pattern in THREAT_PATTERNS:
        matched: list[str] = []
        for phrase in pattern.phrases:
            if phrase.lower() in text_lower:
                matched.append(phrase)
        for keyword in pattern.keywords:
            if _contains_keyword(text_lower, keyword):
                matched.append(keyword)

        if matched:
            result.has_threat = True
            result.matched_categories.append(
                {"category": pattern.category, "level": pattern.default_level, "matched_text": sorted(set(matched))}
            )
            if pattern.default_level == "CRITICAL":
                result.max_level = "CRITICAL"
            elif result.max_level != "CRITICAL":
                result.max_level = "HIGH"

    return result


THREAT_ASSESSMENT_PROMPT = """You are a safety assessment system for a tourist travel app in Vietnam.
The speech-to-text system detected potential threat keywords.

MATCHED THREAT DATA:
{threat_data}

FULL CONVERSATION CONTEXT:
{conversation_context}

Determine if there is a real, present threat to the tourist right now.
Return only valid JSON with:
assessment: CONFIRMED_THREAT | POSSIBLE_THREAT | FALSE_ALARM
reasoning: short English explanation
threat_category: most relevant category or null
recommended_level: CRITICAL | HIGH | NONE
immediate_action: short action description
"""


def _fallback_context_assessment(scan_result: ThreatScanResult, context: list[str]) -> dict:
    combined = " ".join(context).lower()
    past_or_hypothetical = ["yesterday", "last year", "in the news", "movie", "joke"]
    categories = {item.get("category") for item in scan_result.matched_categories}
    shopping_for_sharp_item = (
        "physical_violence" in categories
        and any(marker in combined for marker in ["souvenir", "beautiful", "how much", "bao nhiêu"])
        and any(marker in combined for marker in ["knife", "dao", "ナイフ", "刀"])
    )
    if any(marker in combined for marker in past_or_hypothetical) or shopping_for_sharp_item:
        return {
            "assessment": "FALSE_ALARM",
            "reasoning": "Fallback heuristic found non-immediate context",
            "threat_category": None,
            "recommended_level": "NONE",
            "immediate_action": "Continue normal assistance",
        }
    return {
        "assessment": "POSSIBLE_THREAT",
        "reasoning": "LLM assessment unavailable or unparsable; keeping Tier 1 alert as precaution",
        "threat_category": scan_result.matched_categories[0]["category"] if scan_result.matched_categories else None,
        "recommended_level": scan_result.max_level,
        "immediate_action": "Show threat warning with SOS option",
    }


async def assess_threat_context(scan_result: ThreatScanResult, conversation_context: list[str]) -> dict:
    if scan_result.is_universal_distress:
        return {
            "assessment": "CONFIRMED_THREAT",
            "reasoning": "Universal distress signal detected",
            "threat_category": "universal_distress",
            "recommended_level": "CRITICAL",
            "immediate_action": "Show emergency SOS modal immediately",
        }

    threat_data = "\n".join(
        f"- Category: {m['category']}, Level: {m['level']}, Matched: {m['matched_text']}"
        for m in scan_result.matched_categories
    )
    ctx = "\n".join(conversation_context[-3:]) if conversation_context else "(no prior context)"
    response = await ai_client.chat(
        messages=[
            {
                "role": "system",
                "content": THREAT_ASSESSMENT_PROMPT.format(threat_data=threat_data, conversation_context=ctx),
            },
            {"role": "user", "content": "Assess the current threat level."},
        ],
        response_format={"type": "json_object"},
    )

    try:
        parsed = json.loads(response.content or "")
    except Exception:
        return _fallback_context_assessment(scan_result, conversation_context + [ctx])

    if not isinstance(parsed, dict):
        return _fallback_context_assessment(scan_result, conversation_context + [ctx])

    parsed.setdefault("assessment", "POSSIBLE_THREAT")
    parsed.setdefault("reasoning", "")
    parsed.setdefault("threat_category", scan_result.matched_categories[0]["category"])
    parsed.setdefault("recommended_level", scan_result.max_level)
    parsed.setdefault("immediate_action", "Show threat warning with SOS option")
    return parsed


_session_risk_scores: dict[str, dict] = defaultdict(
    lambda: {
        "total_score": 0.0,
        "category_scores": defaultdict(float),
        "escalation_history": [],
    }
)

RISK_SCORE_WEIGHTS = {
    "CRITICAL": 40.0,
    "HIGH": 20.0,
    "POSSIBLE_THREAT": 10.0,
}
CUMULATIVE_THRESHOLD_HIGH = 30.0
CUMULATIVE_THRESHOLD_CRITICAL = 50.0


def _coerce_json(value: object, default: object) -> object:
    if value is None:
        return default
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return default
    return value


def _final_level_from_score(total_score: float, level: str) -> str:
    if total_score >= CUMULATIVE_THRESHOLD_CRITICAL or level == "CRITICAL":
        return "CRITICAL"
    if total_score >= CUMULATIVE_THRESHOLD_HIGH or level == "HIGH":
        return "HIGH"
    if level == "NONE":
        return "NONE"
    return "MEDIUM"


def _update_session_risk_memory(session_id: str, assessment: dict) -> tuple[str, float]:
    risk = _session_risk_scores[session_id]
    level = assessment.get("recommended_level", "NONE")
    category = assessment.get("threat_category")

    if level == "NONE":
        risk["total_score"] = max(0.0, risk["total_score"] - 2.0)
        return "NONE", risk["total_score"]

    score_delta = RISK_SCORE_WEIGHTS.get(level, 5.0)
    risk["total_score"] += score_delta
    if category:
        risk["category_scores"][category] += score_delta
    risk["escalation_history"].append(
        {"level": level, "category": category, "score_after": risk["total_score"]}
    )

    if risk["total_score"] >= CUMULATIVE_THRESHOLD_CRITICAL or level == "CRITICAL":
        return "CRITICAL", risk["total_score"]
    if risk["total_score"] >= CUMULATIVE_THRESHOLD_HIGH or level == "HIGH":
        return "HIGH", risk["total_score"]
    return "MEDIUM", risk["total_score"]


async def update_session_risk(session_id: str, assessment: dict) -> tuple[str, float]:
    """Persist cumulative risk per session, with an in-memory fallback for tests."""
    level = assessment.get("recommended_level", "NONE")
    category = assessment.get("threat_category")
    try:
        sid = uuid.UUID(session_id)
        pool = get_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT total_score, category_scores, escalation_history
                FROM threat_risk_state
                WHERE session_id = $1
                """,
                sid,
            )
            total_score = float(row["total_score"]) if row else 0.0
            category_scores = _coerce_json(row["category_scores"], {}) if row else {}
            escalation_history = _coerce_json(row["escalation_history"], []) if row else []
            if not isinstance(category_scores, dict):
                category_scores = {}
            if not isinstance(escalation_history, list):
                escalation_history = []

            if level == "NONE":
                total_score = max(0.0, total_score - 2.0)
                final_level = "NONE"
            else:
                score_delta = RISK_SCORE_WEIGHTS.get(level, 5.0)
                total_score += score_delta
                if category:
                    category_scores[category] = float(category_scores.get(category, 0.0)) + score_delta
                escalation_history.append(
                    {"level": level, "category": category, "score_after": total_score}
                )
                escalation_history = escalation_history[-20:]
                final_level = _final_level_from_score(total_score, level)

            await conn.execute(
                """
                INSERT INTO threat_risk_state
                    (session_id, total_score, category_scores, escalation_history, updated_at)
                VALUES ($1, $2, $3, $4, now())
                ON CONFLICT (session_id) DO UPDATE SET
                    total_score = EXCLUDED.total_score,
                    category_scores = EXCLUDED.category_scores,
                    escalation_history = EXCLUDED.escalation_history,
                    updated_at = now()
                """,
                sid,
                total_score,
                json.dumps(category_scores, ensure_ascii=False),
                json.dumps(escalation_history, ensure_ascii=False),
            )
            return final_level, total_score
    except Exception:
        return _update_session_risk_memory(session_id, assessment)


def _confidence(final_level: str, assessment: str) -> float:
    if final_level == "CRITICAL":
        return 0.95 if assessment == "CONFIRMED_THREAT" else 0.88
    if final_level == "HIGH":
        return 0.82
    if final_level == "MEDIUM":
        return 0.62
    return 0.0


async def detect_threat(
    text: str,
    session_id: str,
    conversation_context: list[str] | None = None,
) -> ThreatDetectionResult:
    scan = scan_threat_keywords(text)
    if not scan.has_threat:
        _, cumulative_score = await update_session_risk(session_id, {"recommended_level": "NONE"})
        return ThreatDetectionResult(
            final_level="NONE",
            threat_categories=[],
            assessment="NO_THREAT",
            reasoning="No threat keywords detected",
            show_sos_button=False,
            auto_open_sos_modal=False,
            cumulative_score=cumulative_score,
        )

    assessment = await assess_threat_context(scan, conversation_context or [])
    if assessment.get("assessment") == "FALSE_ALARM":
        _, cumulative_score = await update_session_risk(session_id, {"recommended_level": "NONE"})
        return ThreatDetectionResult(
            final_level="NONE",
            threat_categories=[],
            assessment="FALSE_ALARM",
            reasoning=assessment.get("reasoning", ""),
            show_sos_button=False,
            auto_open_sos_modal=False,
            recommended_action=assessment.get("immediate_action", "Continue normal assistance"),
            cumulative_score=cumulative_score,
        )

    final_level, cumulative_score = await update_session_risk(session_id, assessment)
    categories = sorted({m["category"] for m in scan.matched_categories})
    primary_category = assessment.get("threat_category") or (categories[0] if categories else None)
    show_sos = final_level in {"HIGH", "CRITICAL"}
    return ThreatDetectionResult(
        final_level=final_level,
        threat_categories=categories,
        assessment=assessment.get("assessment", "POSSIBLE_THREAT"),
        reasoning=assessment.get("reasoning", ""),
        show_sos_button=show_sos,
        auto_open_sos_modal=final_level == "CRITICAL",
        primary_threat_category=primary_category,
        confidence=_confidence(final_level, assessment.get("assessment", "POSSIBLE_THREAT")),
        recommended_action=assessment.get("immediate_action", "Show threat warning with SOS option"),
        sos_reason=f"{final_level}: {primary_category}" if show_sos and primary_category else None,
        cumulative_score=cumulative_score,
    )
