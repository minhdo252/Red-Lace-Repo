"""Smart ordering for emergency contacts."""

from __future__ import annotations

from typing import Any


THREAT_TO_SERVICE_PRIORITY: dict[str | None, list[str]] = {
    "robbery_theft": ["police", "general_emergency", "tourist_police", "embassy", "medical"],
    "physical_violence": ["police", "general_emergency", "medical", "tourist_police", "embassy"],
    "unlawful_detention": ["police", "general_emergency", "tourist_police", "embassy", "medical"],
    "medical_emergency": ["medical", "general_emergency", "police", "embassy", "tourist_police"],
    "harassment_sexual": ["police", "general_emergency", "tourist_police", "embassy", "medical"],
    "financial_coercion": ["tourist_police", "police", "general_emergency", "embassy", "medical"],
    "sophisticated_scam": ["tourist_police", "police", "general_emergency", "embassy", "medical"],
    "isolation_disorientation": ["police", "general_emergency", "tourist_police", "medical", "embassy"],
    "universal_distress": ["general_emergency", "police", "medical", "tourist_police", "embassy"],
    None: ["general_emergency", "police", "medical", "tourist_police", "fire", "embassy"],
}


def sort_hotlines_by_threat(
    hotlines: list[dict[str, Any]],
    embassy: dict[str, Any] | None,
    threat_category: str | None,
) -> list[dict[str, Any]]:
    priority_order = THREAT_TO_SERVICE_PRIORITY.get(threat_category, THREAT_TO_SERVICE_PRIORITY[None])

    contacts: list[dict[str, Any]] = [dict(item) for item in hotlines]
    if embassy:
        embassy_entry = dict(embassy)
        embassy_entry["service_type"] = "embassy"
        contacts.append(embassy_entry)

    def sort_key(contact: dict[str, Any]) -> tuple[int, str]:
        service_type = str(contact.get("service_type") or "")
        try:
            rank = priority_order.index(service_type)
        except ValueError:
            rank = 99
        return rank, service_type

    sorted_contacts = sorted(contacts, key=sort_key)
    for index, contact in enumerate(sorted_contacts):
        contact["is_primary"] = index == 0
        contact["priority_rank"] = index + 1
    return sorted_contacts
