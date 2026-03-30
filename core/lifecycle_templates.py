"""
Lifecycle Templates - Optional configuration for different industry/domain types.

This module provides templates for common lifecycle patterns, but the system
is fully generic and can work without any templates.
"""

from typing import Dict, List, Optional

# Example templates (optional - system works without these)
LIFECYCLE_TEMPLATES: Dict[str, Dict] = {
    "procurement": {
        "domain": "manufacturing",
        "common_document_types": ["PO", "CO", "INV", "Contract"],
        "common_event_types": [
            "PO_CREATED",
            "CHANGE_ORDER",
            "INVOICE_RECEIVED",
            "DELIVERY_COMPLETE"
        ],
        "cycle_time_target_days": 18
    },
    "hr": {
        "domain": "human_resources",
        "common_document_types": ["Resume", "Offer", "Contract", "Review"],
        "common_event_types": [
            "APPLICATION_RECEIVED",
            "INTERVIEW_SCHEDULED",
            "OFFER_EXTENDED",
            "ONBOARDING_COMPLETE"
        ],
        "cycle_time_target_days": 30
    },
    "sales": {
        "domain": "business_development",
        "common_document_types": ["Proposal", "Quote", "Contract", "Invoice"],
        "common_event_types": [
            "LEAD_CREATED",
            "PROPOSAL_SENT",
            "CONTRACT_SIGNED",
            "DEAL_CLOSED"
        ],
        "cycle_time_target_days": 45
    },
    "generic": {
        "domain": "general",
        "common_document_types": ["Document", "Report", "File"],
        "common_event_types": [
            "DOCUMENT_CREATED",
            "CHANGE_EVENT",
            "COMPLETION_EVENT"
        ],
        "cycle_time_target_days": 18
    }
}


def get_template(lifecycle_type: str) -> Optional[Dict]:
    """Get lifecycle template by type."""
    return LIFECYCLE_TEMPLATES.get(lifecycle_type)


def list_templates() -> List[str]:
    """List available lifecycle template types."""
    return list(LIFECYCLE_TEMPLATES.keys())


def get_cycle_time_target(lifecycle_type: Optional[str] = None) -> int:
    """Get cycle time target for a lifecycle type (default: 18 days)."""
    if lifecycle_type and lifecycle_type in LIFECYCLE_TEMPLATES:
        return LIFECYCLE_TEMPLATES[lifecycle_type].get("cycle_time_target_days", 18)
    return 18
