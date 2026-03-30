import logging

from fastapi import APIRouter, HTTPException, Query

from api.middleware.auth import require_api_key
from models.outcome import OutcomeCreate, OutcomeResponse
from services.outcome_service import OutcomeService
from services.outcome_extractor import OutcomeExtractor

router = APIRouter(dependencies=[require_api_key()])

service = OutcomeService()
logger = logging.getLogger(__name__)


@router.get("", response_model=list[OutcomeResponse])
def list_outcomes(
    lifecycle_id: str = Query(None, description="Filter by lifecycle ID"),
    outcome_type: str = Query(None, description="Filter by outcome type"),
    limit: int = Query(100, ge=1, le=1000, description="Maximum number of results")
) -> list[OutcomeResponse]:
    """List outcomes with optional filters."""
    try:
        return service.list_outcomes(
            lifecycle_id=lifecycle_id,
            outcome_type=outcome_type,
            limit=limit
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to list outcomes: {str(e)}")


@router.post("", response_model=OutcomeResponse)
def create_outcome(payload: OutcomeCreate) -> OutcomeResponse:
    """Create a new outcome."""
    try:
        return service.create_outcome(payload)
    except ConnectionError as e:
        raise HTTPException(status_code=503, detail="Database unavailable")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to create outcome: {str(e)}")


@router.get("/stats/{lifecycle_id}")
def get_outcome_stats(lifecycle_id: str):
    """Get outcome statistics for a lifecycle."""
    try:
        return service.get_outcome_stats(lifecycle_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get stats: {str(e)}")


@router.post("/retroactive-extraction")
def retroactive_outcome_extraction():
    """
    Retroactively extract outcomes for all existing completed lifecycles.
    
    This endpoint:
    - Finds all lifecycles with status "completed" or "closed"
    - Analyzes their document revisions and events
    - Extracts cost variance, time variance, and other metrics
    - Creates outcome records in PostgreSQL
    
    Returns:
        Dictionary with extraction statistics:
        - processed: Number of lifecycles processed
        - outcomes_created: Total number of outcomes created
        - lifecycles_with_outcomes: Number of lifecycles that had outcomes extracted
        - errors: Number of errors encountered
    """
    try:
        logger.info("Starting retroactive outcome extraction for all completed lifecycles...")
        extractor = OutcomeExtractor()
        stats = extractor.extract_outcomes_for_all_completed_lifecycles()
        
        logger.info(f"Retroactive outcome extraction complete: {stats}")
        
        return {
            "success": True,
            "message": "Retroactive outcome extraction complete",
            "stats": stats
        }
    except Exception as e:
        logger.error(f"Retroactive outcome extraction failed: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Retroactive outcome extraction failed: {str(e)}"
        )
