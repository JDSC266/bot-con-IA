"""
paypal_handler.py - Integración con la API de PayPal (Subscriptions v1)

Flujo:
  1. El usuario ejecuta /subscribe
  2. El bot llama a create_subscription() → obtiene un enlace de aprobación PayPal
  3. El usuario aprueba el pago en PayPal
  4. PayPal llama a nuestro webhook /paypal/webhook con el evento
     BILLING.SUBSCRIPTION.ACTIVATED
  5. El bot activa la suscripción en la base de datos y notifica al usuario
"""
import logging
import requests
from datetime import datetime, timedelta
from config import (
    PAYPAL_CLIENT_ID, PAYPAL_CLIENT_SECRET,
    PAYPAL_MODE, PAYPAL_PLAN_ID,
    SUBSCRIPTION_PRICE, SUBSCRIPTION_CURRENCY,
    WEBHOOK_URL,
)

logger = logging.getLogger(__name__)

PAYPAL_BASE = (
    "https://api-m.paypal.com"
    if PAYPAL_MODE == "live"
    else "https://api-m.sandbox.paypal.com"
)


# ── Autenticación ─────────────────────────────────────────────────────────────

def _get_token() -> str:
    """Obtiene un access token OAuth2 de PayPal."""
    resp = requests.post(
        f"{PAYPAL_BASE}/v1/oauth2/token",
        auth=(PAYPAL_CLIENT_ID, PAYPAL_CLIENT_SECRET),
        data={"grant_type": "client_credentials"},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        timeout=15,
    )
    resp.raise_for_status()
    return resp.json()["access_token"]


def _headers() -> dict:
    return {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {_get_token()}",
        "Prefer": "return=representation",
    }


# ── Suscripciones ─────────────────────────────────────────────────────────────

def create_subscription(user_id: int) -> dict:
    """
    Crea una suscripción PayPal para el usuario.
    Devuelve el JSON completo (incluye enlaces de aprobación).
    """
    payload = {
        "plan_id": PAYPAL_PLAN_ID,
        "custom_id": str(user_id),          # para identificar al usuario en el webhook
        "application_context": {
            "brand_name": "Asistente IA Bot",
            "locale": "es-ES",
            "shipping_preference": "NO_SHIPPING",
            "user_action": "SUBSCRIBE_NOW",
            "payment_method": {
                "payer_selected": "PAYPAL",
                "payee_preferred": "IMMEDIATE_PAYMENT_REQUIRED",
            },
            "return_url": f"{WEBHOOK_URL}/paypal/success",
            "cancel_url": f"{WEBHOOK_URL}/paypal/cancel",
        },
    }
    resp = requests.post(
        f"{PAYPAL_BASE}/v1/billing/subscriptions",
        json=payload,
        headers=_headers(),
        timeout=20,
    )
    resp.raise_for_status()
    return resp.json()


def get_subscription(subscription_id: str) -> dict:
    """Obtiene los detalles de una suscripción PayPal."""
    resp = requests.get(
        f"{PAYPAL_BASE}/v1/billing/subscriptions/{subscription_id}",
        headers=_headers(),
        timeout=15,
    )
    resp.raise_for_status()
    return resp.json()


def cancel_subscription(subscription_id: str,
                        reason: str = "Cancelado por el usuario") -> bool:
    """Cancela una suscripción PayPal. Devuelve True si tuvo éxito."""
    resp = requests.post(
        f"{PAYPAL_BASE}/v1/billing/subscriptions/{subscription_id}/cancel",
        json={"reason": reason},
        headers=_headers(),
        timeout=15,
    )
    return resp.status_code == 204


# ── Configuración inicial (ejecutar UNA VEZ) ──────────────────────────────────

def create_plan_and_product() -> dict:
    """
    Crea el producto y el plan de suscripción mensual en PayPal.
    Ejecuta este método UNA SOLA VEZ mediante setup_paypal.py.
    Guarda el Plan ID resultante en la variable de entorno PAYPAL_PLAN_ID.
    """
    h = _headers()

    # 1) Crear producto
    product_resp = requests.post(
        f"{PAYPAL_BASE}/v1/catalogs/products",
        json={
            "name": "Asistente IA Bot – Suscripción Mensual",
            "description": "Acceso mensual al asistente de IA en Telegram",
            "type": "SERVICE",
            "category": "SOFTWARE",
        },
        headers=h,
        timeout=15,
    )
    product_resp.raise_for_status()
    product_id = product_resp.json()["id"]
    logger.info(f"Producto PayPal creado: {product_id}")

    # 2) Crear plan mensual de 3 €
    plan_resp = requests.post(
        f"{PAYPAL_BASE}/v1/billing/plans",
        json={
            "product_id": product_id,
            "name": "Plan Mensual – Asistente IA",
            "description": f"Suscripción mensual al Asistente de IA ({SUBSCRIPTION_PRICE} {SUBSCRIPTION_CURRENCY}/mes)",
            "status": "ACTIVE",
            "billing_cycles": [
                {
                    "frequency": {"interval_unit": "MONTH", "interval_count": 1},
                    "tenure_type": "REGULAR",
                    "sequence": 1,
                    "total_cycles": 0,       # 0 = sin límite
                    "pricing_scheme": {
                        "fixed_price": {
                            "value": str(SUBSCRIPTION_PRICE),
                            "currency_code": SUBSCRIPTION_CURRENCY,
                        }
                    },
                }
            ],
            "payment_preferences": {
                "auto_bill_outstanding": True,
                "setup_fee": {"value": "0", "currency_code": SUBSCRIPTION_CURRENCY},
                "setup_fee_failure_action": "CONTINUE",
                "payment_failure_threshold": 3,
            },
        },
        headers=h,
        timeout=15,
    )
    plan_resp.raise_for_status()
    plan = plan_resp.json()
    logger.info(f"Plan PayPal creado: {plan['id']}")
    return plan