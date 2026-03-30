from datetime import datetime, timedelta
from typing import List, Dict, Any
from dateutil.parser import parse as parse_date

from fastapi import APIRouter, HTTPException

from api.middleware.auth import require_api_key
from models.prediction import RiskPrediction
from services.prediction_service import PredictionService
from services.lifecycle_service import LifecycleService
from core.database import get_neo4j_connection, get_qdrant_connection
from neo4j import GraphDatabase
from qdrant_client import QdrantClient

router = APIRouter(dependencies=[require_api_key()])

service = PredictionService()
lifecycle_service = LifecycleService()


@router.get("/{lifecycle_id}/risk", response_model=RiskPrediction)
def get_risk(lifecycle_id: str) -> RiskPrediction:
    """Get risk prediction for a lifecycle."""
    import logging
    logger = logging.getLogger(__name__)
    
    try:
        logger.info(f"Getting risk prediction for lifecycle: {lifecycle_id}")
        prediction = service.predict_risk(lifecycle_id)
        logger.info(f"Prediction for {lifecycle_id}: score={prediction.risk_score}, label={prediction.risk_label}, events={len(prediction.drivers)} drivers")
        return prediction
    except Exception as e:
        logger.error(f"Failed to predict risk for {lifecycle_id}: {e}", exc_info=True)
        # Return a default prediction instead of raising an error
        return RiskPrediction(
            lifecycle_id=lifecycle_id,
            risk_score=0.2,
            risk_label="low",
            drivers=[],
            explanation=f"Error generating prediction: {str(e)}. Upload documents to generate risk predictions."
        )


@router.get("/{lifecycle_id}/trends")
def get_trends(lifecycle_id: str) -> Dict[str, Any]:
    """Get risk and volume trends for a lifecycle."""
    try:
        lifecycle = lifecycle_service.get_lifecycle(lifecycle_id)
        
        # Calculate risk trend over time periods
        risk_trend = []
        volume_trend = []
        
        if lifecycle.events and len(lifecycle.events) > 0:
            from datetime import timezone
            import math
            from services.temporal_delta_engine import TemporalDeltaEngine
            
            def normalize_datetime(dt):
                """Normalize datetime to timezone-aware UTC."""
                if dt is None:
                    return None
                if isinstance(dt, str):
                    dt = parse_date(dt)
                if isinstance(dt, datetime):
                    # If timezone-naive, assume UTC
                    if dt.tzinfo is None:
                        dt = dt.replace(tzinfo=timezone.utc)
                    # Convert to UTC
                    return dt.astimezone(timezone.utc)
                return dt
            
            # Normalize all timestamps before sorting
            normalized_events = []
            for e in lifecycle.events:
                normalized_ts = normalize_datetime(e.timestamp)
                # Create a dict with event properties
                event_dict = {
                    "event_id": e.event_id,
                    "event_type": e.event_type,
                    "summary": getattr(e, 'summary', None),
                    "timestamp": normalized_ts
                }
                normalized_events.append(event_dict)
            
            # Sort events by timestamp
            sorted_events = sorted(normalized_events, key=lambda e: e["timestamp"])
            # Build cumulative checkpoints so compressed timelines (same day events) still render meaningful progression.
            total_events = len(sorted_events)
            checkpoint_sizes = [
                max(1, math.ceil(total_events * frac))
                for frac in [0.2, 0.4, 0.6, 0.8, 1.0]
            ]
            labels = ["Start", "P2", "P3", "P4", "Now"]
            delta_engine = TemporalDeltaEngine()

            def _score_events(events_subset: List[Dict[str, Any]]) -> float:
                if not events_subset:
                    return 0.2

                base_risk = 0.2
                event_factor = min(0.15, 0.03 * len(events_subset))
                change_events = sum(
                    1 for e in events_subset
                    if "CHANGE" in e.get("event_type", "").upper() or "MODIFY" in e.get("event_type", "").upper()
                )
                change_factor = min(0.2, 0.05 * change_events)

                # Revision factor using the same delta engine used by prediction scoring.
                revision_analysis = delta_engine.analyze_document_revisions(events_subset)
                total_revisions = sum(rev.get("revision_count", 0) for rev in revision_analysis.get("revisions", []))
                revision_factor = min(0.25, 0.1 * total_revisions)

                timeline_factor = 0.0
                if len(events_subset) > 1:
                    first_ts = normalize_datetime(events_subset[0]["timestamp"])
                    last_ts = normalize_datetime(events_subset[-1]["timestamp"])
                    if first_ts and last_ts:
                        total_days = (last_ts - first_ts).days
                        if total_days > 0:
                            events_per_day = len(events_subset) / total_days
                            timeline_factor = min(0.15, events_per_day * 0.05)
                        else:
                            timeline_factor = 0.1

                return min(0.95, base_risk + event_factor + revision_factor + change_factor + timeline_factor)

            for label, size in zip(labels, checkpoint_sizes):
                subset = sorted_events[:size]
                risk_trend.append({
                    "period": label,
                    "score": round(_score_events(subset), 2),
                })
                volume_trend.append({
                    "period": label,
                    "docs": len(subset),  # cumulative document volume at this checkpoint
                })

            # Ensure "Now" matches the current prediction card exactly.
            current_prediction = service.predict_risk(lifecycle_id)
            if risk_trend:
                now_score = round(current_prediction.risk_score, 2)
                risk_trend[-1]["score"] = now_score
                # Keep the trend visually consistent by avoiding peaks above the current score.
                for i in range(len(risk_trend) - 1):
                    risk_trend[i]["score"] = round(min(risk_trend[i]["score"], now_score), 2)
        else:
            # No events, return default trends with all zeros
            for i in range(5):
                label = f"W-{4-i}" if i < 4 else "Now"
                risk_trend.append({"period": label, "score": 0.2})
                volume_trend.append({"period": label, "docs": 0})
        
        return {
            "risk_trend": risk_trend,
            "volume_trend": volume_trend
        }
    except Exception as e:
        import logging
        logger = logging.getLogger(__name__)
        logger.error(f"Failed to get trends for {lifecycle_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to get trends: {str(e)}")
