"""
main.py - Punto de entrada principal

Ejecuta dos procesos en paralelo:
  1. Flask  → recibe webhooks de PayPal y health-checks de Railway
  2. python-telegram-bot → polling de Telegram
"""
import asyncio
import json
import logging
import threading

from datetime import datetime, timedelta
from flask import Flask, request, jsonify
from telegram import Bot

import database as db
import paypal_handler
from bot import create_app
from config import PORT, TELEGRAM_TOKEN

# ── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    format="%(asctime)s | %(levelname)-8s | %(name)s — %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# ── Flask app ─────────────────────────────────────────────────────────────────
flask_app = Flask(__name__)


@flask_app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok", "timestamp": datetime.utcnow().isoformat()})


@flask_app.route("/paypal/webhook", methods=["POST"])
def paypal_webhook():
    """Recibe y procesa eventos de PayPal."""
    try:
        data       = request.json or {}
        event_type = data.get("event_type", "UNKNOWN")
        resource   = data.get("resource", {})
        logger.info(f"PayPal webhook → {event_type}")

        # ── Suscripción activada ──────────────────────────────────────────
        if event_type == "BILLING.SUBSCRIPTION.ACTIVATED":
            sub_id    = resource.get("id")
            custom_id = resource.get("custom_id")  # contiene user_id

            if sub_id and custom_id:
                user_id = int(custom_id)
                user = db.get_user(user_id)
                
                now = datetime.utcnow()
                base_date = now

                # Revisamos si el usuario existe y tiene días a favor
                if user:
                    if user["subscription_status"] == "active" and user["subscription_end_date"]:
                        sub_end = datetime.fromisoformat(user["subscription_end_date"])
                        if sub_end > base_date:
                            base_date = sub_end
                    elif user["subscription_status"] == "trial" and user["trial_end_date"]:
                        trial_end = datetime.fromisoformat(user["trial_end_date"])
                        if trial_end > base_date:
                            base_date = trial_end

                # Sumamos el mes de suscripción a la fecha base correcta
                end_date = base_date + timedelta(days=31)
                
                db.update_subscription(user_id, "active", sub_id, end_date)
                db.activate_payment(sub_id)
                logger.info(f"✅ Suscripción activada → user {user_id}")
                asyncio.run(_notify(user_id,
                    "🎉 *¡Tu suscripción está activa!*\n\n"
                    "Ya puedes usar el Asistente de IA sin limitaciones.\n"
                    "Tus días se han sumado correctamente a tu saldo actual. ¡Gracias! 😊"
                ))

        # ── Pago recurrente completado ────────────────────────────────────
        elif event_type == "PAYMENT.SALE.COMPLETED":
            billing_id = resource.get("billing_agreement_id")
            if billing_id:
                user = db.get_user_by_subscription(billing_id)
                if user:
                    uid      = user["user_id"]
                    current  = datetime.fromisoformat(
                        user.get("subscription_end_date") or datetime.utcnow().isoformat()
                    )
                    new_end  = max(current, datetime.utcnow()) + timedelta(days=31)
                    db.update_subscription(uid, "active", billing_id, new_end)
                    logger.info(f"🔄 Suscripción renovada → user {uid}")

        # ── Suscripción cancelada ─────────────────────────────────────────
        elif event_type == "BILLING.SUBSCRIPTION.CANCELLED":
            sub_id = resource.get("id")
            user   = db.get_user_by_subscription(sub_id) if sub_id else None
            if user:
                db.update_subscription(user["user_id"], "cancelled")
                logger.info(f"❌ Suscripción cancelada → user {user['user_id']}")
                asyncio.run(_notify(user["user_id"],
                    "😔 Tu suscripción ha sido *cancelada*.\n"
                    "Puedes volver a suscribirte en cualquier momento con /subscribe."
                ))

        # ── Suscripción suspendida (pago fallido) ─────────────────────────
        elif event_type == "BILLING.SUBSCRIPTION.SUSPENDED":
            sub_id = resource.get("id")
            user   = db.get_user_by_subscription(sub_id) if sub_id else None
            if user:
                db.update_subscription(user["user_id"], "suspended")
                logger.info(f"⚠️ Suscripción suspendida → user {user['user_id']}")
                asyncio.run(_notify(user["user_id"],
                    "⚠️ Tu suscripción ha sido *suspendida* por un pago fallido.\n"
                    "Por favor actualiza tu método de pago en PayPal."
                ))

        return jsonify({"status": "ok"}), 200

    except Exception as e:
        logger.error(f"Error en webhook PayPal: {e}", exc_info=True)
        return jsonify({"status": "error", "detail": str(e)}), 500


@flask_app.route("/paypal/success")
def paypal_success():
    sub_id = request.args.get("subscription_id", "")
    return f"""<!DOCTYPE html>
<html lang="es">
<head>
  <meta charset="UTF-8">
  <title>¡Pago exitoso!</title>
  <style>
    body {{ font-family: Arial, sans-serif; text-align: center;
            padding: 60px 20px; background: #f0fdf4; color: #166534; }}
    h1 {{ font-size: 2.5rem; }}
    p  {{ font-size: 1.1rem; color: #374151; }}
    .id{{ font-size: .85rem; color: #9ca3af; margin-top: 30px; }}
  </style>
</head>
<body>
  <h1>✅ ¡Suscripción activada!</h1>
  <p>Tu pago se ha completado correctamente.</p>
  <p>Vuelve a Telegram — recibirás un mensaje de confirmación en segundos.</p>
  <p class="id">ID: {sub_id}</p>
</body>
</html>""", 200


@flask_app.route("/paypal/cancel")
def paypal_cancel():
    return """<!DOCTYPE html>
<html lang="es">
<head>
  <meta charset="UTF-8">
  <title>Pago cancelado</title>
  <style>
    body {{ font-family: Arial, sans-serif; text-align: center;
            padding: 60px 20px; background: #fef2f2; color: #991b1b; }}
    h1 {{ font-size: 2.5rem; }}
    p  {{ font-size: 1.1rem; color: #374151; }}
  </style>
</head>
<body>
  <h1>❌ Pago cancelado</h1>
  <p>El proceso de pago fue cancelado.</p>
  <p>Vuelve a Telegram y usa /subscribe si quieres intentarlo de nuevo.</p>
</body>
</html>""", 200


# ── Notificaciones asíncronas ─────────────────────────────────────────────────

async def _notify(user_id: int, text: str) -> None:
    try:
        bot = Bot(token=TELEGRAM_TOKEN)
        await bot.send_message(chat_id=user_id, text=text, parse_mode="Markdown")
    except Exception as e:
        logger.error(f"Error notificando al usuario {user_id}: {e}")


# ── Runner ────────────────────────────────────────────────────────────────────

def _run_flask() -> None:
    logger.info(f"Flask escuchando en el puerto {PORT} …")
    flask_app.run(host="0.0.0.0", port=PORT, debug=False, use_reloader=False)


def main() -> None:
    # 1. Base de datos
    db.init_db()
    logger.info("Base de datos lista.")

    # 2. Flask en hilo secundario
    t = threading.Thread(target=_run_flask, daemon=True)
    t.start()

    # 3. Bot de Telegram en el hilo principal (polling)
    app = create_app()
    logger.info("Bot de Telegram iniciado (polling) …")
    app.run_polling(allowed_updates=["message", "callback_query"])


if __name__ == "__main__":
    main()