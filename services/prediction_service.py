from datetime import datetime
from models.prediction import RiskPrediction
from services.lifecycle_service import LifecycleService
from services.temporal_delta_engine import TemporalDeltaEngine


class PredictionService:
    def __init__(self) -> None:
        self.lifecycle_service = LifecycleService()
        self.delta_engine = TemporalDeltaEngine()

    def predict_risk(self, lifecycle_id: str) -> RiskPrediction:
        lifecycle = self.lifecycle_service.get_lifecycle(lifecycle_id)
        
        # Handle case where lifecycle doesn't exist or has no events
        if not lifecycle or lifecycle.status == "not_found":
            return RiskPrediction(
                lifecycle_id=lifecycle_id,
                risk_score=0.2,
                risk_label="low",
                drivers=[],
                explanation="Lifecycle not found or has no events. Upload documents to generate predictions."
            )
        
        from datetime import timezone
        from dateutil.parser import parse as parse_date
        
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
        
        events = []
        for event in lifecycle.events:
            normalized_ts = normalize_datetime(event.timestamp)
            events.append({
                "timestamp": normalized_ts,
                "event_type": event.event_type
            })
        
        # If no events, return a default prediction
        if not events:
            return RiskPrediction(
                lifecycle_id=lifecycle_id,
                risk_score=0.2,
                risk_label="low",
                drivers=[],
                explanation="No events recorded yet. Upload documents to generate risk predictions."
            )
        
        deltas = self.delta_engine.compute_deltas(events)
        
        # Analyze document revisions for risk indicators
        revision_analysis = self.delta_engine.analyze_document_revisions(events)
        revision_count = len(revision_analysis.get("revisions", []))
        total_revisions = sum(rev.get("revision_count", 0) for rev in revision_analysis.get("revisions", []))
        
        # Get cost variance from lifecycle metrics if available
        try:
            from api.routes.lifecycles import get_lifecycle_metrics
            metrics = get_lifecycle_metrics(lifecycle_id)
            cost_variance = abs(metrics.get("cost_variance_percent", 0))
        except:
            cost_variance = 0
        
        # Calculate risk score based on multiple factors
        base_risk = 0.2
        
        # Factor 1: Event count (more events = more complexity)
        event_factor = min(0.15, 0.03 * len(events))
        
        # Factor 2: Document revisions (revisions indicate scope creep)
        revision_factor = min(0.25, 0.1 * total_revisions)
        
        # Factor 3: Change events (change orders, modifications)
        change_events = sum(1 for e in events if "CHANGE" in e["event_type"].upper() or "MODIFY" in e["event_type"].upper())
        change_factor = min(0.2, 0.05 * change_events)
        
        # Factor 4: Cost variance (high variance = high risk)
        variance_factor = min(0.3, cost_variance / 100.0 * 0.5)  # 50% variance = 0.15 risk
        
        # Factor 5: Timeline compression (if events are close together, indicates rush)
        if len(events) > 1:
            sorted_events = sorted(events, key=lambda e: normalize_datetime(e["timestamp"]))
            first_ts = normalize_datetime(sorted_events[0]["timestamp"])
            last_ts = normalize_datetime(sorted_events[-1]["timestamp"])
            if first_ts and last_ts:
                total_days = (last_ts - first_ts).days
                # If many events in short time, higher risk
                if total_days > 0:
                    events_per_day = len(events) / total_days
                    timeline_factor = min(0.15, events_per_day * 0.05)
                else:
                    timeline_factor = 0.1  # All events same day = rush
            else:
                timeline_factor = 0
        else:
            timeline_factor = 0
        
        # Calculate final risk score
        risk_score = min(0.95, base_risk + event_factor + revision_factor + change_factor + variance_factor + timeline_factor)
        risk_label = "high" if risk_score >= 0.7 else "medium" if risk_score >= 0.4 else "low"
        
        # Build explanation
        explanation_parts = []
        if total_revisions > 0:
            explanation_parts.append(f"{total_revisions} document revision(s) detected")
        if cost_variance > 5:
            explanation_parts.append(f"Cost variance: {cost_variance:.1f}%")
        if change_events > 0:
            explanation_parts.append(f"{change_events} change event(s)")
        if len(events) > 3:
            explanation_parts.append(f"High event frequency ({len(events)} events)")
        
        explanation = ". ".join(explanation_parts) if explanation_parts else self.delta_engine.summarize(events)
        
        # Derive drivers from actual event data (generic pattern-based analysis)
        drivers = []
        if not events:
            drivers = []
        else:
            # Analyze event types to identify risk drivers (pattern-based, not type-specific)
            event_types = [e["event_type"].upper() for e in events]
            
            # Generic risk indicators (works for any industry)
            change_events_count = sum(1 for et in event_types if "CHANGE" in et or "MODIFY" in et or "UPDATE" in et)
            risk_events = sum(1 for et in event_types if "RISK" in et or "ALERT" in et or "WARNING" in et)
            delay_events = sum(1 for et in event_types if "DELAY" in et or "LATE" in et or "OVERDUE" in et)
            error_events = sum(1 for et in event_types if "ERROR" in et or "FAIL" in et or "ISSUE" in et)
            
            # Count unique event types (diversity indicates complexity)
            unique_types = len(set(event_types))
            
            # Add revision-based drivers
            if total_revisions > 0:
                drivers.append(f"Multiple document revisions ({total_revisions} revision(s))")
            if cost_variance > 5:
                drivers.append(f"Significant cost variance (+{cost_variance:.1f}%)")
            if change_events_count > 0:
                drivers.append(f"Change events ({change_events_count} occurrences)")
            if risk_events > 0:
                drivers.append(f"Risk indicators ({risk_events} alerts)")
            if delay_events > 0:
                drivers.append(f"Timing issues ({delay_events} delays)")
            if error_events > 0:
                drivers.append(f"Error events ({error_events} issues)")
            if unique_types > 5:
                drivers.append(f"High event diversity ({unique_types} unique types)")
            if len(events) > 3 and len(events) / max(1, (normalize_datetime(events[-1]["timestamp"]) - normalize_datetime(events[0]["timestamp"])).days) > 0.5:
                drivers.append("High change frequency (multiple changes within short timeframe)")
            
            # If no specific drivers found, use generic ones based on event count
            if not drivers and len(events) > 0:
                drivers.append(f"Event frequency ({len(events)} total events)")
        
        return RiskPrediction(
            lifecycle_id=lifecycle_id,
            risk_score=risk_score,
            risk_label=risk_label,
            drivers=drivers,
            explanation=explanation,
        )
