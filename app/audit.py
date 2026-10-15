import sqlite3
from pathlib import Path
from typing import Any, Dict, List
from app.schemas import AuditEvent


class AuditLogger:
    def __init__(self, db_path: str = "./data/audit.db"):
        self.db_path = db_path
        if db_path != ":memory:":
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._init_schema()

    def _init_schema(self) -> None:
        with self._conn:
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS audit_events (
                    request_id TEXT PRIMARY KEY,
                    timestamp TEXT NOT NULL,
                    app_profile TEXT NOT NULL,
                    requested_provider TEXT NOT NULL,
                    selected_provider TEXT NOT NULL,
                    model TEXT NOT NULL,
                    status_category TEXT NOT NULL,
                    fallback_used INTEGER NOT NULL,
                    fallback_reason TEXT,
                    latency_ms REAL NOT NULL,
                    prompt_tokens INTEGER NOT NULL,
                    completion_tokens INTEGER NOT NULL
                )
                """
            )

    def record(self, event: AuditEvent) -> None:
        with self._conn:
            self._conn.execute(
                """
                INSERT INTO audit_events (
                    request_id, timestamp, app_profile, requested_provider,
                    selected_provider, model, status_category, fallback_used,
                    fallback_reason, latency_ms, prompt_tokens, completion_tokens
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event.request_id,
                    event.timestamp,
                    event.app_profile,
                    event.requested_provider,
                    event.selected_provider,
                    event.model,
                    event.status_category,
                    int(event.fallback_used),
                    event.fallback_reason,
                    event.latency_ms,
                    event.prompt_tokens,
                    event.completion_tokens,
                ),
            )

    def list_events(self, limit: int = 20) -> List[AuditEvent]:
        cursor = self._conn.cursor()
        cursor.execute(
            """
            SELECT request_id, timestamp, app_profile, requested_provider,
                   selected_provider, model, status_category, fallback_used,
                   fallback_reason, latency_ms, prompt_tokens, completion_tokens
            FROM audit_events
            ORDER BY timestamp DESC
            LIMIT ?
            """,
            (limit,),
        )
        rows = cursor.fetchall()
        return [
            AuditEvent(
                request_id=r[0],
                timestamp=r[1],
                app_profile=r[2],
                requested_provider=r[3],
                selected_provider=r[4],
                model=r[5],
                status_category=r[6],
                fallback_used=bool(r[7]),
                fallback_reason=r[8],
                latency_ms=r[9],
                prompt_tokens=r[10],
                completion_tokens=r[11],
            )
            for r in rows
        ]

    def compute_metrics(self) -> Dict[str, Any]:
        events = self.list_events(limit=1000)
        total = len(events)
        rate_limit_events = [e for e in events if e.fallback_reason == "rate_limit"]
        rate_limit_recovered = [
            e for e in rate_limit_events if e.status_category == "fallback_success"
        ]
        fallback_latencies = [e.latency_ms for e in rate_limit_recovered]
        ollama_latencies = [
            e.latency_ms for e in events if e.selected_provider == "ollama"
        ]
        blocked_attempts = [
            e
            for e in events
            if e.status_category
            in {
                "provider_denied",
                "model_denied",
                "data_classification_denied",
                "rag_disabled",
                "secret_detected",
                "auth_error",
                "quota_exhausted",
            }
        ]

        recovery_pct = (
            round((len(rate_limit_recovered) / len(rate_limit_events)) * 100, 1)
            if rate_limit_events
            else 0.0
        )

        return {
            "total_recorded_requests": total,
            "rate_limit_events_total": len(rate_limit_events),
            "rate_limit_fallback_recovery_pct": recovery_pct,
            "avg_fallback_latency_ms": (
                round(sum(fallback_latencies) / len(fallback_latencies), 2)
                if fallback_latencies
                else 0.0
            ),
            "avg_ollama_latency_ms": (
                round(sum(ollama_latencies) / len(ollama_latencies), 2)
                if ollama_latencies
                else 0.0
            ),
            "blocked_unauthorized_or_policy_attempts": len(blocked_attempts),
            "prompt_or_output_columns_in_db": 0,
        }

    def dump_raw_database_text(self) -> str:
        cursor = self._conn.cursor()
        cursor.execute("SELECT * FROM audit_events")
        return str(cursor.fetchall())