import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Generator, List, Optional

from .schemas import AnalysisRecord


try:
    import psycopg
    from psycopg.rows import dict_row
except Exception:  # noqa: BLE001
    psycopg = None
    dict_row = None


DB_PATH = Path(os.getenv("DB_PATH", str(Path(__file__).resolve().parent.parent / "data" / "analyses.db")))
DATABASE_URL = os.getenv("DATABASE_URL", "").strip()
IS_POSTGRES = DATABASE_URL.startswith("postgresql://") or DATABASE_URL.startswith("postgres://")


def _now() -> str:
    return datetime.utcnow().isoformat() + "Z"


def _created_at_to_dt(value: str) -> datetime:
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


def _require_pg() -> None:
    if psycopg is None or dict_row is None:
        raise RuntimeError("PostgreSQL is configured but psycopg is not installed.")


def _is_unique_violation(exc: Exception) -> bool:
    name = exc.__class__.__name__.lower()
    msg = str(exc).lower()
    return "unique" in name or "duplicate" in msg or "unique constraint" in msg


def init_db() -> None:
    if IS_POSTGRES:
        _require_pg()
        with get_conn() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS tenants (
                    id BIGSERIAL PRIMARY KEY,
                    company TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS users (
                    id BIGSERIAL PRIMARY KEY,
                    tenant_id BIGINT NOT NULL REFERENCES tenants(id),
                    email TEXT UNIQUE NOT NULL,
                    password_hash TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS subscriptions (
                    id BIGSERIAL PRIMARY KEY,
                    tenant_id BIGINT UNIQUE NOT NULL REFERENCES tenants(id),
                    stripe_customer_id TEXT,
                    stripe_subscription_id TEXT,
                    status TEXT NOT NULL DEFAULT 'inactive',
                    plan TEXT NOT NULL DEFAULT 'free',
                    updated_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS analyses (
                    id BIGSERIAL PRIMARY KEY,
                    tenant_id BIGINT NOT NULL DEFAULT 0,
                    user_id BIGINT NOT NULL DEFAULT 0,
                    repo_url TEXT NOT NULL,
                    ci_provider TEXT NOT NULL DEFAULT 'github',
                    profile_json TEXT NOT NULL,
                    files_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )
            conn.execute("ALTER TABLE analyses ADD COLUMN IF NOT EXISTS tenant_id BIGINT NOT NULL DEFAULT 0")
            conn.execute("ALTER TABLE analyses ADD COLUMN IF NOT EXISTS user_id BIGINT NOT NULL DEFAULT 0")
            conn.execute("ALTER TABLE analyses ADD COLUMN IF NOT EXISTS ci_provider TEXT NOT NULL DEFAULT 'github'")
            conn.commit()
        return

    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS tenants (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                company TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tenant_id INTEGER NOT NULL,
                email TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY (tenant_id) REFERENCES tenants(id)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS subscriptions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tenant_id INTEGER UNIQUE NOT NULL,
                stripe_customer_id TEXT,
                stripe_subscription_id TEXT,
                status TEXT NOT NULL DEFAULT 'inactive',
                plan TEXT NOT NULL DEFAULT 'free',
                updated_at TEXT NOT NULL,
                FOREIGN KEY (tenant_id) REFERENCES tenants(id)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS analyses (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tenant_id INTEGER NOT NULL DEFAULT 0,
                user_id INTEGER NOT NULL DEFAULT 0,
                repo_url TEXT NOT NULL,
                ci_provider TEXT NOT NULL DEFAULT 'github',
                profile_json TEXT NOT NULL,
                files_json TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )
        _migrate_analyses_table_sqlite(conn)
        conn.commit()


def _migrate_analyses_table_sqlite(conn: sqlite3.Connection) -> None:
    columns = {row[1] for row in conn.execute("PRAGMA table_info(analyses)").fetchall()}
    if "tenant_id" not in columns:
        conn.execute("ALTER TABLE analyses ADD COLUMN tenant_id INTEGER NOT NULL DEFAULT 0")
    if "user_id" not in columns:
        conn.execute("ALTER TABLE analyses ADD COLUMN user_id INTEGER NOT NULL DEFAULT 0")
    if "ci_provider" not in columns:
        conn.execute("ALTER TABLE analyses ADD COLUMN ci_provider TEXT NOT NULL DEFAULT 'github'")


@contextmanager
def get_conn() -> Generator[Any, None, None]:
    if IS_POSTGRES:
        _require_pg()
        conn = psycopg.connect(DATABASE_URL, row_factory=dict_row)
        try:
            yield conn
        finally:
            conn.close()
        return

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()


def _last_id(cur: Any) -> int:
    if IS_POSTGRES:
        row = cur.fetchone()
        if not row:
            return 0
        if isinstance(row, dict):
            return int(row["id"])
        return int(row[0])
    return int(cur.lastrowid)


def _row_get(row: Any, key: str) -> Any:
    if isinstance(row, dict):
        return row[key]
    return row[key]


def save_analysis(tenant_id: int, user_id: int, repo_url: str, ci_provider: str, profile: Dict[str, object], files: Dict[str, str]) -> int:
    created_at = _now()
    with get_conn() as conn:
        if IS_POSTGRES:
            cur = conn.execute(
                """
                INSERT INTO analyses (tenant_id, user_id, repo_url, ci_provider, profile_json, files_json, created_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                RETURNING id
                """,
                (tenant_id, user_id, repo_url, ci_provider, json.dumps(profile), json.dumps(files), created_at),
            )
            new_id = _last_id(cur)
        else:
            cur = conn.execute(
                """
                INSERT INTO analyses (tenant_id, user_id, repo_url, ci_provider, profile_json, files_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (tenant_id, user_id, repo_url, ci_provider, json.dumps(profile), json.dumps(files), created_at),
            )
            new_id = _last_id(cur)
        conn.commit()
        return new_id


def list_recent(tenant_id: int, limit: int = 20) -> List[AnalysisRecord]:
    with get_conn() as conn:
        if IS_POSTGRES:
            rows = conn.execute(
                """
                SELECT id, tenant_id, user_id, repo_url, ci_provider, profile_json, files_json, created_at
                FROM analyses
                WHERE tenant_id = %s
                ORDER BY id DESC
                LIMIT %s
                """,
                (tenant_id, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT id, tenant_id, user_id, repo_url, ci_provider, profile_json, files_json, created_at
                FROM analyses
                WHERE tenant_id = ?
                ORDER BY id DESC
                LIMIT ?
                """,
                (tenant_id, limit),
            ).fetchall()

    records: List[AnalysisRecord] = []
    for row in rows:
        records.append(
            AnalysisRecord(
                id=int(_row_get(row, "id")),
                tenant_id=int(_row_get(row, "tenant_id")),
                user_id=int(_row_get(row, "user_id")),
                repo_url=str(_row_get(row, "repo_url")),
                ci_provider=str(_row_get(row, "ci_provider")),
                profile=json.loads(_row_get(row, "profile_json")),
                files=json.loads(_row_get(row, "files_json")),
                created_at=_created_at_to_dt(_row_get(row, "created_at")),
            )
        )
    return records


def create_user(company: str, email: str, password_hash: str) -> Dict[str, object]:
    created_at = _now()
    email_norm = email.lower().strip()
    company_clean = company.strip()

    with get_conn() as conn:
        if IS_POSTGRES:
            tenant_cur = conn.execute(
                "INSERT INTO tenants (company, created_at) VALUES (%s, %s) RETURNING id",
                (company_clean, created_at),
            )
            tenant_id = _last_id(tenant_cur)
            try:
                user_cur = conn.execute(
                    """
                    INSERT INTO users (tenant_id, email, password_hash, created_at)
                    VALUES (%s, %s, %s, %s)
                    RETURNING id
                    """,
                    (tenant_id, email_norm, password_hash, created_at),
                )
            except Exception as exc:  # noqa: BLE001
                conn.rollback()
                if _is_unique_violation(exc):
                    raise ValueError("EMAIL_EXISTS") from exc
                raise
            user_id = _last_id(user_cur)
            conn.execute(
                """
                INSERT INTO subscriptions (tenant_id, status, plan, updated_at)
                VALUES (%s, 'inactive', 'free', %s)
                """,
                (tenant_id, created_at),
            )
        else:
            tenant_cur = conn.execute(
                "INSERT INTO tenants (company, created_at) VALUES (?, ?)",
                (company_clean, created_at),
            )
            tenant_id = _last_id(tenant_cur)
            try:
                user_cur = conn.execute(
                    """
                    INSERT INTO users (tenant_id, email, password_hash, created_at)
                    VALUES (?, ?, ?, ?)
                    """,
                    (tenant_id, email_norm, password_hash, created_at),
                )
            except sqlite3.IntegrityError as exc:
                conn.rollback()
                raise ValueError("EMAIL_EXISTS") from exc
            user_id = _last_id(user_cur)
            conn.execute(
                """
                INSERT INTO subscriptions (tenant_id, status, plan, updated_at)
                VALUES (?, 'inactive', 'free', ?)
                """,
                (tenant_id, created_at),
            )
        conn.commit()

    return {"id": user_id, "tenant_id": tenant_id, "email": email_norm, "company": company_clean}


def get_user_by_email(email: str) -> Optional[Dict[str, object]]:
    email_norm = email.lower().strip()
    with get_conn() as conn:
        if IS_POSTGRES:
            row = conn.execute(
                """
                SELECT u.id, u.tenant_id, u.email, u.password_hash, t.company
                FROM users u
                JOIN tenants t ON t.id = u.tenant_id
                WHERE u.email = %s
                """,
                (email_norm,),
            ).fetchone()
        else:
            row = conn.execute(
                """
                SELECT u.id, u.tenant_id, u.email, u.password_hash, t.company
                FROM users u
                JOIN tenants t ON t.id = u.tenant_id
                WHERE u.email = ?
                """,
                (email_norm,),
            ).fetchone()
    if not row:
        return None
    return {
        "id": int(_row_get(row, "id")),
        "tenant_id": int(_row_get(row, "tenant_id")),
        "email": str(_row_get(row, "email")),
        "password_hash": str(_row_get(row, "password_hash")),
        "company": str(_row_get(row, "company")),
    }


def get_user_by_id(user_id: int) -> Optional[Dict[str, object]]:
    with get_conn() as conn:
        if IS_POSTGRES:
            row = conn.execute(
                """
                SELECT u.id, u.tenant_id, u.email, u.password_hash, t.company
                FROM users u
                JOIN tenants t ON t.id = u.tenant_id
                WHERE u.id = %s
                """,
                (user_id,),
            ).fetchone()
        else:
            row = conn.execute(
                """
                SELECT u.id, u.tenant_id, u.email, u.password_hash, t.company
                FROM users u
                JOIN tenants t ON t.id = u.tenant_id
                WHERE u.id = ?
                """,
                (user_id,),
            ).fetchone()
    if not row:
        return None
    return {
        "id": int(_row_get(row, "id")),
        "tenant_id": int(_row_get(row, "tenant_id")),
        "email": str(_row_get(row, "email")),
        "password_hash": str(_row_get(row, "password_hash")),
        "company": str(_row_get(row, "company")),
    }


def update_subscription_by_customer(
    stripe_customer_id: str,
    stripe_subscription_id: Optional[str],
    status: str,
    plan: str,
) -> None:
    with get_conn() as conn:
        if IS_POSTGRES:
            conn.execute(
                """
                UPDATE subscriptions
                SET stripe_subscription_id = %s, status = %s, plan = %s, updated_at = %s
                WHERE stripe_customer_id = %s
                """,
                (stripe_subscription_id, status, plan, _now(), stripe_customer_id),
            )
        else:
            conn.execute(
                """
                UPDATE subscriptions
                SET stripe_subscription_id = ?, status = ?, plan = ?, updated_at = ?
                WHERE stripe_customer_id = ?
                """,
                (stripe_subscription_id, status, plan, _now(), stripe_customer_id),
            )
        conn.commit()


def link_customer_to_tenant(tenant_id: int, stripe_customer_id: str) -> None:
    with get_conn() as conn:
        if IS_POSTGRES:
            conn.execute(
                """
                UPDATE subscriptions
                SET stripe_customer_id = %s, updated_at = %s
                WHERE tenant_id = %s
                """,
                (stripe_customer_id, _now(), tenant_id),
            )
        else:
            conn.execute(
                """
                UPDATE subscriptions
                SET stripe_customer_id = ?, updated_at = ?
                WHERE tenant_id = ?
                """,
                (stripe_customer_id, _now(), tenant_id),
            )
        conn.commit()


def get_subscription(tenant_id: int) -> Dict[str, object]:
    with get_conn() as conn:
        if IS_POSTGRES:
            row = conn.execute(
                """
                SELECT tenant_id, stripe_customer_id, stripe_subscription_id, status, plan, updated_at
                FROM subscriptions
                WHERE tenant_id = %s
                """,
                (tenant_id,),
            ).fetchone()
        else:
            row = conn.execute(
                """
                SELECT tenant_id, stripe_customer_id, stripe_subscription_id, status, plan, updated_at
                FROM subscriptions
                WHERE tenant_id = ?
                """,
                (tenant_id,),
            ).fetchone()
    if not row:
        return {"tenant_id": tenant_id, "status": "inactive", "plan": "free"}
    return {
        "tenant_id": int(_row_get(row, "tenant_id")),
        "stripe_customer_id": _row_get(row, "stripe_customer_id"),
        "stripe_subscription_id": _row_get(row, "stripe_subscription_id"),
        "status": str(_row_get(row, "status")),
        "plan": str(_row_get(row, "plan")),
        "updated_at": str(_row_get(row, "updated_at")),
    }
