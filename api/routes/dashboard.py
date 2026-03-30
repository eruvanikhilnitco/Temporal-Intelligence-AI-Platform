from fastapi import APIRouter, HTTPException
from datetime import datetime, timedelta
from typing import Dict, Any, List
from dateutil.parser import parse as parse_date

from api.middleware.auth import require_api_key
from core.database import get_neo4j_connection, get_qdrant_connection
from neo4j import GraphDatabase
from qdrant_client import QdrantClient

router = APIRouter(dependencies=[require_api_key()])


def get_dashboard_stats() -> Dict[str, Any]:
    """Get aggregated dashboard statistics."""
    stats = {
        "active_lifecycles": 0,
        "total_lifecycles": 0,
        "open_risks": 0,
        "documents_indexed": 0,
        "documents_last_24h": 0,
        "total_events": 0,
        "events_last_7d": 0,
        "average_cycle_time": 0,
        "risk_drivers": [],
        "recent_activity": [],
        "lifecycle_status_breakdown": {},
        "event_type_distribution": {},
        "top_lifecycles": []
    }
    
    try:
        # Get Neo4j connection
        neo4j_config = get_neo4j_connection()
        driver = GraphDatabase.driver(
            neo4j_config.uri,
            auth=(neo4j_config.user, neo4j_config.password)
        )
        
        with driver.session() as session:
            # Count total and active lifecycles
            result = session.run("""
                MATCH (l:Lifecycle)
                RETURN count(l) as total,
                       sum(CASE WHEN l.status IN ['active', 'pending', 'in_progress'] THEN 1 ELSE 0 END) as active
            """)
            record = result.single()
            stats["total_lifecycles"] = record["total"] if record else 0
            stats["active_lifecycles"] = record["active"] if record else 0
            
            # Get lifecycle status breakdown
            result = session.run("""
                MATCH (l:Lifecycle)
                RETURN l.status as status, count(l) as count
            """)
            status_breakdown = {}
            for record in result:
                status = record["status"] or "unknown"
                status_breakdown[status] = record["count"]
            stats["lifecycle_status_breakdown"] = status_breakdown
            
            # Count total events
            result = session.run("""
                MATCH (e:Event)
                RETURN count(e) as count
            """)
            record = result.single()
            stats["total_events"] = record["count"] if record else 0
            
            # Count events in last 7 days (simplified - count all events for now)
            # In a real implementation, you'd filter by timestamp properly
            # For now, we'll use a rough estimate based on total events
            stats["events_last_7d"] = max(0, stats["total_events"] // 4)  # Rough estimate
            
            # Get event type distribution
            result = session.run("""
                MATCH (e:Event)
                RETURN e.event_type as event_type, count(e) as count
                ORDER BY count DESC
                LIMIT 10
            """)
            event_distribution = {}
            for record in result:
                event_type = record["event_type"] or "UNKNOWN"
                event_distribution[event_type] = record["count"]
            stats["event_type_distribution"] = event_distribution
            
            # Calculate average cycle time (get timestamps as strings and calculate in Python)
            result = session.run("""
                MATCH (l:Lifecycle)-[:HAS_EVENT]->(e:Event)
                RETURN l.lifecycle_id as lifecycle_id, 
                       toString(e.timestamp) as timestamp
                ORDER BY l.lifecycle_id, e.timestamp ASC
            """)
            lifecycle_events = {}
            for record in result:
                lc_id = record["lifecycle_id"]
                ts_str = record["timestamp"]
                if lc_id not in lifecycle_events:
                    lifecycle_events[lc_id] = []
                if ts_str:
                    lifecycle_events[lc_id].append(ts_str)
            
            # Calculate cycle times
            cycle_times = []
            for lc_id, timestamps in lifecycle_events.items():
                if len(timestamps) > 1:
                    try:
                        first = parse_date(timestamps[0])
                        last = parse_date(timestamps[-1])
                        diff = (last - first).days
                        if diff > 0:
                            cycle_times.append(diff)
                    except:
                        continue
            
            if cycle_times:
                stats["average_cycle_time"] = round(sum(cycle_times) / len(cycle_times), 1)
            
            # Get top lifecycles by event count
            result = session.run("""
                MATCH (l:Lifecycle)-[:HAS_EVENT]->(e:Event)
                WITH l, count(e) as event_count
                RETURN l.lifecycle_id as lifecycle_id, 
                       l.status as status,
                       event_count
                ORDER BY event_count DESC
                LIMIT 5
            """)
            top_lifecycles = []
            for record in result:
                top_lifecycles.append({
                    "lifecycle_id": record["lifecycle_id"],
                    "status": record["status"],
                    "event_count": record["event_count"]
                })
            stats["top_lifecycles"] = top_lifecycles
            
            # Count lifecycles with high risk (we'll use events as proxy)
            result = session.run("""
                MATCH (l:Lifecycle)-[:HAS_EVENT]->(e:Event)
                WHERE e.event_type CONTAINS 'RISK' OR e.event_type CONTAINS 'ALERT'
                RETURN count(DISTINCT l) as count
            """)
            record = result.single()
            stats["open_risks"] = record["count"] if record else 0
            
            # Get recent activity (last 10 events)
            result = session.run("""
                MATCH (l:Lifecycle)-[:HAS_EVENT]->(e:Event)
                RETURN l.lifecycle_id as lifecycle_id, 
                       e.event_type as event_type,
                       e.summary as summary,
                       toString(e.timestamp) as timestamp
                ORDER BY e.timestamp DESC
                LIMIT 10
            """)
            activities = []
            for record in result:
                activities.append({
                    "lifecycle_id": record["lifecycle_id"],
                    "event_type": record["event_type"],
                    "summary": record["summary"],
                    "timestamp": record["timestamp"]
                })
            stats["recent_activity"] = activities
            
            # Get risk drivers (lifecycles with multiple change orders or delays)
            result = session.run("""
                MATCH (l:Lifecycle)-[:HAS_EVENT]->(e:Event)
                WHERE e.event_type CONTAINS 'CHANGE' OR e.event_type CONTAINS 'DELAY'
                WITH l, count(e) as change_count
                WHERE change_count > 1
                RETURN l.lifecycle_id as lifecycle_id, change_count
                ORDER BY change_count DESC
                LIMIT 3
            """)
            risk_drivers = []
            for record in result:
                risk_drivers.append(f"Lifecycle {record['lifecycle_id']}: {record['change_count']} change events")
            stats["risk_drivers"] = risk_drivers
        
        driver.close()
    except Exception as e:
        # If Neo4j fails, use defaults
        pass
    
    try:
        # Get Qdrant connection for document counts
        from qdrant_client import QdrantClient
        qdrant_config = get_qdrant_connection()
        qdrant_client = QdrantClient(host=qdrant_config.host, port=qdrant_config.port)
        
        # Count total documents
        collections = qdrant_client.get_collections()
        for collection in collections.collections:
            if collection.name == "documents":
                stats["documents_indexed"] = collection.points_count
                break
        
        # For documents in last 24h, we'd need to query by timestamp in metadata
        # This is a simplified version
        stats["documents_last_24h"] = 0
        
    except Exception as e:
        # If Qdrant fails, use defaults
        pass
    
    return stats


@router.get("/stats")
def get_stats() -> Dict[str, Any]:
    """Get dashboard statistics."""
    try:
        return get_dashboard_stats()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get dashboard stats: {str(e)}")


@router.get("/notifications")
def get_notifications() -> List[Dict[str, Any]]:
    """Get recent notifications from lifecycle events."""
    notifications = []
    try:
        neo4j_config = get_neo4j_connection()
        driver = GraphDatabase.driver(
            neo4j_config.uri,
            auth=(neo4j_config.user, neo4j_config.password)
        )
        
        with driver.session() as session:
            # Get recent events that could be notifications
            result = session.run("""
                MATCH (l:Lifecycle)-[:HAS_EVENT]->(e:Event)
                WHERE e.event_type CONTAINS 'RISK' 
                   OR e.event_type CONTAINS 'ALERT'
                   OR e.event_type CONTAINS 'CHANGE'
                   OR e.event_type CONTAINS 'INVOICE'
                RETURN l.lifecycle_id as lifecycle_id,
                       e.event_type as event_type,
                       e.summary as summary,
                       toString(e.timestamp) as timestamp
                ORDER BY e.timestamp DESC
                LIMIT 10
            """)
            
            for record in result:
                event_type = record["event_type"] or "Event"
                summary = record["summary"] or "No details"
                lifecycle_id = record["lifecycle_id"]
                timestamp_str = record["timestamp"]
                
                # Determine notification type and title
                if "RISK" in event_type or "ALERT" in event_type:
                    notif_type = "risk"
                    title = f"Lifecycle {lifecycle_id} flagged"
                elif "INVOICE" in event_type:
                    notif_type = "document"
                    title = f"New invoice ingested"
                else:
                    notif_type = "system"
                    title = f"Lifecycle {lifecycle_id} updated"
                
                # Calculate time ago
                try:
                    if timestamp_str:
                        ts = datetime.fromisoformat(timestamp_str.replace('Z', '+00:00'))
                        now = datetime.utcnow()
                        diff = now - ts.replace(tzinfo=None) if ts.tzinfo else now - ts
                        if diff.total_seconds() < 3600:
                            time_ago = f"{int(diff.total_seconds() / 60)}m ago"
                        elif diff.total_seconds() < 86400:
                            time_ago = f"{int(diff.total_seconds() / 3600)}h ago"
                        else:
                            time_ago = "Today"
                    else:
                        time_ago = "Recently"
                except:
                    time_ago = "Recently"
                
                notifications.append({
                    "id": f"n-{len(notifications) + 1}",
                    "title": title,
                    "detail": summary[:100] if len(summary) > 100 else summary,
                    "time": time_ago,
                    "type": notif_type,
                    "lifecycleId": lifecycle_id
                })
        
        driver.close()
    except Exception as e:
        # Return empty list on error
        pass
    
    return notifications
