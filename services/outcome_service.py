import logging
import uuid
from typing import List, Optional

import psycopg2
from psycopg2.extras import RealDictCursor

from core.database import get_postgres_connection
from models.outcome import OutcomeCreate, OutcomeResponse

logger = logging.getLogger(__name__)


class OutcomeService:
    def __init__(self):
        try:
            pg_config = get_postgres_connection()
            self.conn_string = (
                f"host={pg_config.host} "
                f"port={pg_config.port} "
                f"dbname={pg_config.database} "
                f"user={pg_config.user} "
                f"password={pg_config.password}"
            )
            self._ensure_table()
            logger.info("Connected to PostgreSQL")
        except Exception as e:
            logger.error(f"Failed to connect to PostgreSQL: {e}")
            self.conn_string = None

    def _get_connection(self):
        """Get a PostgreSQL connection."""
        if not self.conn_string:
            raise ConnectionError("PostgreSQL not configured")
        return psycopg2.connect(self.conn_string)

    def _ensure_table(self):
        """Ensure the outcomes table exists."""
        if not self.conn_string:
            return

        try:
            with self._get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        CREATE TABLE IF NOT EXISTS outcomes (
                            outcome_id VARCHAR(255) PRIMARY KEY,
                            lifecycle_id VARCHAR(255) NOT NULL,
                            outcome_type VARCHAR(100) NOT NULL,
                            value DOUBLE PRECISION NOT NULL,
                            recorded_at TIMESTAMP NOT NULL,
                            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                        );
                        CREATE INDEX IF NOT EXISTS idx_outcomes_lifecycle 
                            ON outcomes(lifecycle_id);
                        CREATE INDEX IF NOT EXISTS idx_outcomes_type 
                            ON outcomes(outcome_type);
                    """)
                    conn.commit()
        except Exception as e:
            logger.error(f"Failed to ensure outcomes table: {e}")

    def list_outcomes(
        self,
        lifecycle_id: Optional[str] = None,
        outcome_type: Optional[str] = None,
        limit: int = 100
    ) -> List[OutcomeResponse]:
        """List outcomes with optional filters."""
        if not self.conn_string:
            return []

        try:
            with self._get_connection() as conn:
                with conn.cursor(cursor_factory=RealDictCursor) as cur:
                    query = "SELECT * FROM outcomes WHERE 1=1"
                    params = []

                    if lifecycle_id:
                        query += " AND lifecycle_id = %s"
                        params.append(lifecycle_id)

                    if outcome_type:
                        query += " AND outcome_type = %s"
                        params.append(outcome_type)

                    query += " ORDER BY recorded_at DESC LIMIT %s"
                    params.append(limit)

                    cur.execute(query, params)
                    rows = cur.fetchall()

                    return [
                        OutcomeResponse(
                            outcome_id=row["outcome_id"],
                            lifecycle_id=row["lifecycle_id"],
                            outcome_type=row["outcome_type"],
                            value=float(row["value"]),
                            recorded_at=row["recorded_at"]
                        )
                        for row in rows
                    ]
        except Exception as e:
            logger.error(f"Failed to list outcomes: {e}")
            return []

    def create_outcome(self, payload: OutcomeCreate) -> OutcomeResponse:
        """Create a new outcome."""
        if not self.conn_string:
            raise ConnectionError("PostgreSQL not configured")

        outcome_id = str(uuid.uuid4())
        
        try:
            with self._get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        INSERT INTO outcomes (outcome_id, lifecycle_id, outcome_type, value, recorded_at)
                        VALUES (%s, %s, %s, %s, %s)
                    """, (
                        outcome_id,
                        payload.lifecycle_id,
                        payload.outcome_type,
                        payload.value,
                        payload.recorded_at
                    ))
                    conn.commit()

            return OutcomeResponse(
                outcome_id=outcome_id,
                **payload.model_dump()
            )
        except Exception as e:
            logger.error(f"Failed to create outcome: {e}")
            raise

    def get_outcome_stats(self, lifecycle_id: str) -> dict:
        """Get outcome statistics for a lifecycle."""
        if not self.conn_string:
            return {}

        try:
            with self._get_connection() as conn:
                with conn.cursor(cursor_factory=RealDictCursor) as cur:
                    cur.execute("""
                        SELECT 
                            outcome_type,
                            COUNT(*) as count,
                            AVG(value) as avg_value,
                            SUM(value) as total_value,
                            MIN(value) as min_value,
                            MAX(value) as max_value
                        FROM outcomes
                        WHERE lifecycle_id = %s
                        GROUP BY outcome_type
                    """, (lifecycle_id,))
                    rows = cur.fetchall()

                    return {
                        row["outcome_type"]: {
                            "count": row["count"],
                            "avg": float(row["avg_value"]) if row["avg_value"] else 0,
                            "total": float(row["total_value"]) if row["total_value"] else 0,
                            "min": float(row["min_value"]) if row["min_value"] else 0,
                            "max": float(row["max_value"]) if row["max_value"] else 0,
                        }
                        for row in rows
                    }
        except Exception as e:
            logger.error(f"Failed to get outcome stats: {e}")
            return {}
