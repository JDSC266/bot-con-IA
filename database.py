"""
database.py - Gestión de la base de datos SQLite
Tablas: users | conversations | payments
"""
import os
import sqlite3
import json
import logging
from datetime import datetime, timedelta
from config import TRIAL_DAYS, DATABASE_PATH, ADMIN_IDS

logger = logging.getLogger(__name__)

# ── Conexión ──────────────────────────────────────────────────────────────────

def get_connection() -> sqlite3.Connection:
    # 1. Extraemos la carpeta de la ruta y la creamos si no existe
    carpeta = os.path.dirname(DATABASE_PATH)
    if carpeta:
        os.makedirs(carpeta, exist_ok=True)

    # 2. Conectamos y configuramos la base de datos exactamente como la tenías
    conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")   # mejor concurrencia
    return conn


# ── Inicialización ────────────────────────────────────────────────────────────

def init_db() -> None:
    """Crea las tablas si no existen."""
    conn = get_connection()
    cur  = conn.cursor()

    cur.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            user_id             INTEGER PRIMARY KEY,
            username            TEXT    DEFAULT '',
            first_name          TEXT    DEFAULT '',
            last_name           TEXT    DEFAULT '',
            registered_at       TEXT    NOT NULL,
            trial_end_date      TEXT    NOT NULL,
            subscription_status TEXT    NOT NULL DEFAULT 'trial',
            subscription_end_date TEXT,
            paypal_subscription_id TEXT,
            is_blocked          INTEGER NOT NULL DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS conversations (
            user_id    INTEGER PRIMARY KEY,
            messages   TEXT    NOT NULL DEFAULT '[]',
            updated_at TEXT    NOT NULL
        );

        CREATE TABLE IF NOT EXISTS payments (
            id                   INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id              INTEGER NOT NULL,
            paypal_subscription_id TEXT,
            paypal_order_id      TEXT,
            amount               REAL    NOT NULL DEFAULT 3.0,
            currency             TEXT    NOT NULL DEFAULT 'EUR',
            status               TEXT    NOT NULL DEFAULT 'pending',
            created_at           TEXT    NOT NULL,
            activated_at         TEXT
        );
    """)

    conn.commit()
    conn.close()
    logger.info("Base de datos inicializada correctamente.")


# ── Usuarios ──────────────────────────────────────────────────────────────────

def get_user(user_id: int) -> dict | None:
    conn = get_connection()
    cur  = conn.cursor()
    cur.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
    row  = cur.fetchone()
    conn.close()
    return dict(row) if row else None


def register_user(user_id: int, username: str,
                  first_name: str, last_name: str = "") -> dict:
    """Registra un usuario nuevo con periodo de prueba gratuita."""
    conn = get_connection()
    cur  = conn.cursor()

    now       = datetime.utcnow()
    trial_end = now + timedelta(days=TRIAL_DAYS)

    cur.execute("""
        INSERT OR IGNORE INTO users
            (user_id, username, first_name, last_name,
             registered_at, trial_end_date, subscription_status)
        VALUES (?, ?, ?, ?, ?, ?, 'trial')
    """, (user_id, username, first_name, last_name,
          now.isoformat(), trial_end.isoformat()))

    conn.commit()
    conn.close()
    return get_user(user_id)


def check_access(user_id: int) -> tuple[bool, str, int]:
    """
    Comprueba si el usuario puede usar el bot.
    Devuelve: (tiene_acceso, estado, días_restantes)

    Estados posibles:
        'not_registered' | 'blocked' | 'trial' | 'subscribed' |
        'trial_expired'  | 'expired' | 'pending'
    """
    # ── Administradores: acceso ilimitado y gratuito siempre ──────────────────
    if user_id in ADMIN_IDS:
        return True, "admin", 99999

    user = get_user(user_id)

    if not user:
        return False, "not_registered", 0

    if user["is_blocked"]:
        return False, "blocked", 0

    now = datetime.utcnow()

    # ── Suscripción activa ─────────────────────────────────────────────────
    if user["subscription_status"] == "active" and user["subscription_end_date"]:
        end = datetime.fromisoformat(user["subscription_end_date"])
        if end > now:
            # Añadimos + 1 para que el día actual cuente
            return True, "subscribed", (end - now).days + 1 
        else:
            _set_status(user_id, "expired")
            return False, "expired", 0

    # ── Pendiente de confirmación PayPal ──────────────────────────────────
    if user["subscription_status"] == "pending":
        return False, "pending", 0

    # ── Periodo de prueba ─────────────────────────────────────────────────
    if user["trial_end_date"]:
        trial_end = datetime.fromisoformat(user["trial_end_date"])
        if trial_end > now:
            # Y aquí está el otro + 1 agregado
            return True, "trial", (trial_end - now).days + 1
        else:
            if user["subscription_status"] == "trial":
                _set_status(user_id, "trial_expired")
            return False, "trial_expired", 0

    return False, "unknown", 0


def _set_status(user_id: int, status: str) -> None:
    conn = get_connection()
    conn.execute("UPDATE users SET subscription_status=? WHERE user_id=?",
                 (status, user_id))
    conn.commit()
    conn.close()


def update_subscription(user_id: int, status: str,
                        subscription_id: str | None = None,
                        end_date: datetime | None = None) -> None:
    """Actualiza el estado de suscripción de un usuario."""
    conn = get_connection()
    cur  = conn.cursor()

    if subscription_id and end_date:
        cur.execute("""
            UPDATE users
            SET subscription_status=?, paypal_subscription_id=?, subscription_end_date=?
            WHERE user_id=?
        """, (status, subscription_id, end_date.isoformat(), user_id))

    elif subscription_id:
        cur.execute("""
            UPDATE users
            SET subscription_status=?, paypal_subscription_id=?
            WHERE user_id=?
        """, (status, subscription_id, user_id))

    else:
        cur.execute("UPDATE users SET subscription_status=? WHERE user_id=?",
                    (status, user_id))

    conn.commit()
    conn.close()


def get_user_by_subscription(subscription_id: str) -> dict | None:
    conn = get_connection()
    cur  = conn.cursor()
    cur.execute("SELECT * FROM users WHERE paypal_subscription_id=?", (subscription_id,))
    row  = cur.fetchone()
    conn.close()
    return dict(row) if row else None


def get_all_users() -> list[dict]:
    conn = get_connection()
    cur  = conn.cursor()
    cur.execute("SELECT * FROM users")
    rows = cur.fetchall()
    conn.close()
    return [dict(r) for r in rows]


def block_user(user_id: int, blocked: bool = True) -> None:
    conn = get_connection()
    conn.execute("UPDATE users SET is_blocked=? WHERE user_id=?",
                 (1 if blocked else 0, user_id))
    conn.commit()
    conn.close()


# ── Conversaciones ────────────────────────────────────────────────────────────

def get_conversation(user_id: int) -> list:
    conn = get_connection()
    cur  = conn.cursor()
    cur.execute("SELECT messages FROM conversations WHERE user_id=?", (user_id,))
    row  = cur.fetchone()
    conn.close()
    return json.loads(row["messages"]) if row else []


def save_conversation(user_id: int, messages: list) -> None:
    """Guarda el historial de conversación (últimos 20 mensajes)."""
    if len(messages) > 20:
        messages = messages[-20:]

    conn = get_connection()
    conn.execute("""
        INSERT OR REPLACE INTO conversations (user_id, messages, updated_at)
        VALUES (?, ?, ?)
    """, (user_id, json.dumps(messages), datetime.utcnow().isoformat()))
    conn.commit()
    conn.close()


def clear_conversation(user_id: int) -> None:
    conn = get_connection()
    conn.execute("DELETE FROM conversations WHERE user_id=?", (user_id,))
    conn.commit()
    conn.close()


# ── Pagos ─────────────────────────────────────────────────────────────────────

def save_payment(user_id: int, subscription_id: str | None = None,
                 order_id: str | None = None, amount: float = 3.0,
                 currency: str = "EUR", status: str = "pending") -> None:
    conn = get_connection()
    conn.execute("""
        INSERT INTO payments
            (user_id, paypal_subscription_id, paypal_order_id,
             amount, currency, status, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (user_id, subscription_id, order_id, amount, currency, status,
          datetime.utcnow().isoformat()))
    conn.commit()
    conn.close()


def activate_payment(subscription_id: str) -> None:
    conn = get_connection()
    conn.execute("""
        UPDATE payments SET status='active', activated_at=?
        WHERE paypal_subscription_id=?
    """, (datetime.utcnow().isoformat(), subscription_id))
    conn.commit()
    conn.close()