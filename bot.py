import os
import logging
import requests
from datetime import datetime, timedelta
from telegram.error import BadRequest
from config import (
    TELEGRAM_TOKEN, TRIAL_DAYS, SUBSCRIPTION_PRICE,
    PAYPAL_CLIENT_ID, PAYPAL_PLAN_ID, ADMIN_IDS, DATABASE_PATH,
    RAILWAY_API_TOKEN, RAILWAY_ENVIRONMENT_ID, RAILWAY_SERVICE_ID
)

from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup, BotCommand,
)
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    CallbackQueryHandler, filters, ContextTypes,
)
from telegram.constants import ChatAction

import database as db
import claude_api
import paypal_handler
from config import (
    TELEGRAM_TOKEN, TRIAL_DAYS, SUBSCRIPTION_PRICE,
    PAYPAL_CLIENT_ID, PAYPAL_PLAN_ID, ADMIN_IDS,
)

logger = logging.getLogger(__name__)


# ── Utilidades de texto ───────────────────────────────────────────────────────

def _status_text(status: str, days: int) -> str:
    mapping = {
        "admin":        "👑 *Administrador* — acceso ilimitado y gratuito.",
        "trial":        f"🟡 *Prueba gratuita activa* — te quedan *{days} día(s)*.",
        "subscribed":   f"✅ *Suscripción activa* — te quedan *{days} día(s)* en este período.",
        "trial_expired":"🔴 *Prueba gratuita finalizada.* Suscríbete para seguir usando el bot.",
        "expired":      "🔴 *Suscripción expirada.* Renueva para continuar.",
        "pending":      "⏳ *Pago pendiente de confirmación.* Avisa en cuanto PayPal lo confirme.",
        "blocked":      "🚫 Tu cuenta ha sido bloqueada. Contacta al administrador.",
    }
    return mapping.get(status, "❓ Estado desconocido.")


def _subscribe_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(f"💳 Suscribirme – €{SUBSCRIPTION_PRICE}/mes",
                              callback_data="subscribe")],
    ])


# ── /start ────────────────────────────────────────────────────────────────────

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    existing = db.get_user(user.id)

    if not existing:
        db.register_user(user.id, user.username or "",
                         user.first_name, user.last_name or "")

    _, status, days = db.check_access(user.id)
    status_line = _status_text(status, days)

    msg = (
        f"¡Hola, *{user.first_name}*! 👋\n\n"
        f"Soy tu *Asistente de IA* — puedo ayudarte con casi cualquier cosa:\n\n"
        f"• 💬 Conversaciones y preguntas\n"
        f"• ✍️ Redacción de textos y correos\n"
        f"• 💻 Código y programación\n"
        f"• 🌍 Traducción e idiomas\n"
        f"• 📊 Análisis y resúmenes\n\n"
        f"🎉 *¡Tienes {TRIAL_DAYS} días de prueba gratuita!*\n\n"
        f"{status_line}\n\n"
        f"Solo escríbeme lo que necesites y te ayudaré.\n\n"
        f"Comandos: /status · /subscribe · /reset · /help"
    )

    kb = _subscribe_keyboard() if status in ("trial_expired", "expired") else None
    await update.message.reply_text(msg, parse_mode="Markdown", reply_markup=kb)

# ── /status ───────────────────────────────────────────────────────────────────

async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user    = db.get_user(user_id)

    if not user:
        await update.message.reply_text(
            "No estás registrado. Usa /start para comenzar."
        )
        return

    _, status, days = db.check_access(user_id)
    registered = datetime.fromisoformat(user["registered_at"]).strftime("%d/%m/%Y")
    trial_end  = datetime.fromisoformat(user["trial_end_date"]).strftime("%d/%m/%Y")

    text = (
        f"📊 *Estado de tu cuenta*\n\n"
        f"{_status_text(status, days)}\n\n"
        f"📅 Registro: {registered}\n"
        f"⏱ Fin prueba gratuita: {trial_end}"
    )

    kb = _subscribe_keyboard() if status in ("trial_expired", "expired") else None
    await update.message.reply_text(text, parse_mode="Markdown", reply_markup=kb)


# ── /subscribe ────────────────────────────────────────────────────────────────

async def cmd_subscribe(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await _send_subscribe(update.message.reply_text, update.effective_user.id)


async def _send_subscribe(reply_fn, user_id: int):
    """Genera el enlace de suscripción PayPal y lo envía al usuario."""

    if not PAYPAL_CLIENT_ID or not PAYPAL_PLAN_ID:
        await reply_fn(
            "⚠️ El sistema de pagos no está configurado todavía.\n"
            "Contacta al administrador."
        )
        return

    # Verificar si ya tiene acceso gratuito o suscripción activa
    _, status, days = db.check_access(user_id)
    if status == "admin":
        await reply_fn(
            "👑 *Eres administrador* — tienes acceso gratuito e ilimitado. No necesitas suscribirte.",
            parse_mode="Markdown",
        )
        return
    if status == "subscribed":
        await reply_fn(
            f"✅ *Ya tienes una suscripción activa* con {days} día(s) restantes.",
            parse_mode="Markdown",
        )
        return

    try:
        sub  = paypal_handler.create_subscription(user_id)
        link = next(
            (l["href"] for l in sub.get("links", []) if l["rel"] == "approve"),
            None,
        )

        if not link:
            raise ValueError("No se encontró enlace de aprobación en la respuesta de PayPal.")

        sub_id = sub["id"]
        db.save_payment(user_id, subscription_id=sub_id)
        db.update_subscription(user_id, "pending", sub_id)

        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("💳 Pagar con PayPal", url=link)],
        ])
        await reply_fn(
            f"💰 *Suscripción mensual — €{SUBSCRIPTION_PRICE}*\n\n"
            f"Pulsa el botón para completar el pago con PayPal.\n\n"
            f"✔️ La suscripción se activará automáticamente.\n"
            f"🔄 Se renueva cada mes de forma automática.",
            parse_mode="Markdown",
            reply_markup=kb,
        )

    except Exception as e:
        logger.error(f"Error al crear suscripción PayPal para {user_id}: {e}")
        await reply_fn(
            "❌ No se pudo conectar con PayPal. Inténtalo de nuevo más tarde."
        )


# ── /cancel ───────────────────────────────────────────────────────────────────

async def cmd_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user    = db.get_user(user_id)

    if not user or not user.get("paypal_subscription_id"):
        await update.message.reply_text(
            "No tienes ninguna suscripción activa para cancelar."
        )
        return

    try:
        ok = paypal_handler.cancel_subscription(user["paypal_subscription_id"])
        if ok:
            db.update_subscription(user_id, "cancelled")
            await update.message.reply_text(
                "😔 Tu suscripción ha sido *cancelada*.\n\n"
                "Podrás seguir usándola hasta que expire el período actual.\n"
                "Usa /subscribe si quieres volver en otro momento.",
                parse_mode="Markdown",
            )
        else:
            await update.message.reply_text(
                "❌ No se pudo cancelar en PayPal. Inténtalo desde tu cuenta PayPal."
            )
    except Exception as e:
        logger.error(f"Error cancelando suscripción: {e}")
        await update.message.reply_text("❌ Error al cancelar. Inténtalo más tarde.")


# ── /reset ────────────────────────────────────────────────────────────────────

async def cmd_reset(update: Update, context: ContextTypes.DEFAULT_TYPE):
    db.clear_conversation(update.effective_user.id)
    await update.message.reply_text(
        "🔄 Historial de conversación borrado. ¡Empecemos de cero!"
    )


# ── /help ─────────────────────────────────────────────────────────────────────

async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🤖 *Asistente de IA — Ayuda*\n\n"
        "Escríbeme cualquier mensaje y te responderé.\n\n"
        "*Comandos:*\n"
        "• /start — Iniciar el bot\n"
        "• /status — Ver tu estado de suscripción\n"
        "• /subscribe — Suscribirte por €3/mes\n"
        "• /cancel — Cancelar tu suscripción\n"
        "• /reset — Borrar historial de conversación\n"
        "• /help — Esta ayuda\n\n"
        "*¿Qué puedo hacer?*\n"
        "Responder preguntas, redactar textos, ayudar con código, traducir, "
        "analizar datos, resumir documentos y mucho más.",
        parse_mode="Markdown",
    )


# ── /admin ────────────────────────────────────────────────────────────────────

async def cmd_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Panel de administración (solo para ADMIN_IDS)."""
    if update.effective_user.id not in ADMIN_IDS:
        await update.message.reply_text("⛔ No tienes permisos.")
        return

    users = db.get_all_users()
    total  = len(users)
    trial  = sum(1 for u in users if u["subscription_status"] == "trial")
    active = sum(1 for u in users if u["subscription_status"] == "active")
    expired = sum(1 for u in users if u["subscription_status"] in ("trial_expired", "expired"))

    await update.message.reply_text(
        f"🛠 *Panel Admin*\n\n"
        f"👥 Total usuarios: *{total}*\n"
        f"🟡 En prueba: *{trial}*\n"
        f"✅ Suscritos: *{active}*\n"
        f"🔴 Expirados: *{expired}*\n\n"
        f"Comandos admin:\n"
        f"`/block <user_id>` — Bloquear usuario\n"
        f"`/unblock <user_id>` — Desbloquear usuario\n"
        f"`/grant <user_id> <días>` — Dar días de suscripción gratis",
        parse_mode="Markdown",
    )

# ── /database ──────────────────────────────────────────────────────────────────

async def cmd_getdb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Envía el archivo de la base de datos al administrador."""
    if update.effective_user.id not in ADMIN_IDS:
        return
    
    try:
        # Abre el archivo de la base de datos y lo envía
        with open(DATABASE_PATH, 'rb') as file:
            await update.message.reply_document(
                document=file, 
                filename="bot_database.db",
                caption="💾 Aquí tienes la copia actual de la base de datos."
            )
    except FileNotFoundError:
        await update.message.reply_text("❌ El archivo de la base de datos aún no existe.")
    except Exception as e:
        await update.message.reply_text(f"❌ Error al enviar la base de datos: {e}")


async def cmd_block(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS:
        return
    try:
        uid = int(context.args[0])
        db.block_user(uid, True)
        await update.message.reply_text(f"✅ Usuario {uid} bloqueado.")
    except (IndexError, ValueError):
        await update.message.reply_text("Uso: /block <user_id>")


async def cmd_unblock(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS:
        return
    try:
        uid = int(context.args[0])
        db.block_user(uid, False)
        await update.message.reply_text(f"✅ Usuario {uid} desbloqueado.")
    except (IndexError, ValueError):
        await update.message.reply_text("Uso: /unblock <user_id>")


async def cmd_grant(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS:
        return
    try:
        uid  = int(context.args[0])
        days = int(context.args[1])

        # 1. Obtener los datos actuales del usuario
        user = db.get_user(uid)
        if not user:
            await update.message.reply_text(f"❌ El usuario {uid} no existe en la base de datos.")
            return

        now = datetime.utcnow()
        base_date = now

        # 2. Revisar si tiene una suscripción activa y usar esa fecha como base
        if user["subscription_status"] == "active" and user["subscription_end_date"]:
            sub_end = datetime.fromisoformat(user["subscription_end_date"])
            if sub_end > base_date:
                base_date = sub_end

        # 3. O revisar si está en su prueba gratuita y usar esa fecha como base
        elif user["subscription_status"] == "trial" and user["trial_end_date"]:
            trial_end = datetime.fromisoformat(user["trial_end_date"])
            if trial_end > base_date:
                base_date = trial_end

        # 4. Ahora sí, sumamos los días a la fecha que le correspondía
        new_end = base_date + timedelta(days=days)
        
        # Guardamos en la BD usando tu ID manual
        fake_sub_id = f"manual_{uid}"
        db.update_subscription(uid, "active", subscription_id=fake_sub_id, end_date=new_end)
        db.save_payment(uid, subscription_id=fake_sub_id, amount=0.0, status="active")
        
        await update.message.reply_text(
            f"✅ Se sumaron {days} días al usuario {uid}.\n"
            f"💾 Guardado con el ID: {fake_sub_id}"
        )
    except (IndexError, ValueError):
        await update.message.reply_text("Uso: /grant <user_id> <días>")


# ── Mensajes de texto ─────────────────────────────────────────────────────────

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text    = update.message.text

    # Registrar si aún no existe
    if not db.get_user(user_id):
        u = update.effective_user
        db.register_user(user_id, u.username or "", u.first_name, u.last_name or "")

    has_access, status, days = db.check_access(user_id)

    if not has_access:
        msgs = {
            "trial_expired": (
                f"⏰ *Tu prueba gratuita ha finalizado.*\n\n"
                f"Para seguir usando el Asistente de IA, suscríbete "
                f"por solo *€{SUBSCRIPTION_PRICE}/mes*. 👇"
            ),
            "expired": (
                f"🔴 *Tu suscripción ha expirado.*\n\n"
                f"Renueva por *€{SUBSCRIPTION_PRICE}/mes* para continuar. 👇"
            ),
            "pending": (
                "⏳ Tu pago está pendiente de confirmación.\n"
                "Normalmente tarda unos segundos. Inténtalo de nuevo en un momento."
            ),
            "blocked": "🚫 Tu cuenta ha sido bloqueada. Contacta al administrador.",
        }
        msg = msgs.get(status, "No puedes usar el bot. Usa /start.")
        kb  = _subscribe_keyboard() if status in ("trial_expired", "expired") else None
        await update.message.reply_text(msg, parse_mode="Markdown", reply_markup=kb)
        return

    # Indicador de escritura
    await context.bot.send_chat_action(
        chat_id=update.effective_chat.id, action=ChatAction.TYPING
    )

    try:
        history  = db.get_conversation(user_id)
        reply, updated = claude_api.get_response(history, text)
        db.save_conversation(user_id, updated)

        # Aviso si la prueba está por expirar
        if status == "trial" and days <= 3:
            reply += (
                f"\n\n⚠️ _Tu prueba gratuita expira en {days} día(s). "
                f"Usa /subscribe para continuar._"
            )

        # Intentamos enviar con Markdown
        try:
            await update.message.reply_text(reply, parse_mode="Markdown")
        except BadRequest as e:
            # Si el error es de formato (parse entities), enviamos como texto plano
            if "parse entities" in str(e).lower():
                await update.message.reply_text(reply)
            else:
                raise e # Si es otro tipo de BadRequest, lo lanzamos
            
    except Exception as e:
        logger.error(f"Error inesperado procesando mensaje de {user_id}: {e}")
        await update.message.reply_text(
            "❌ Ocurrió un error inesperado. Por favor inténtalo de nuevo."
        )


# ── Callbacks (botones inline) ────────────────────────────────────────────────

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == "subscribe":
        await _send_subscribe(query.message.reply_text, query.from_user.id)

# ── Subit tu Database (.db) ───────────────────────────────────────────────────

async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Permite al administrador restaurar la base de datos enviando el archivo .db"""
    # 1. Bloqueo de seguridad: solo los administradores pueden hacer esto
    if update.effective_user.id not in ADMIN_IDS:
        return

    doc = update.message.document
    
    # 2. Verificamos que el archivo enviado sea realmente una base de datos
    if doc.file_name.endswith('.db'):
        try:
            msg = await update.message.reply_text("⏳ Instalando copia de seguridad...")
            
            # 3. Descargamos el archivo que enviaste
            file = await context.bot.get_file(doc.file_id)
            
            # 4. Limpieza de caché de SQLite (Archivos WAL y SHM)
            # Esto es vital para que la nueva base de datos no se corrompa al sobrescribir
            wal_path = f"{DATABASE_PATH}-wal"
            shm_path = f"{DATABASE_PATH}-shm"
            if os.path.exists(wal_path):
                os.remove(wal_path)
            if os.path.exists(shm_path):
                os.remove(shm_path)
            
            # 5. Reemplazamos el archivo principal de la base de datos
            await file.download_to_drive(DATABASE_PATH)
            
            await msg.edit_text(
                "✅ *¡Copia de seguridad restaurada con éxito!*\n\n"
                "⚠️ _Recomendación:_ Ve a tu panel de Railway y dale al botón "
                "*Restart* de tu servicio para asegurar que la memoria se limpie por completo.",
                parse_mode="Markdown"
            )
            
        except Exception as e:
            await update.message.reply_text(f"❌ Error al restaurar: {e}")

# ── Redespliego del bot ───────────────────────────────────────────────────────

async def cmd_redespliege(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Fuerza un redespliegue completo (Redeploy) a través de la API de Railway."""
    if update.effective_user.id not in ADMIN_IDS:
        return

    if not RAILWAY_API_TOKEN:
        await update.message.reply_text("❌ Falta configurar RAILWAY_API_TOKEN en Railway.")
        return

    await update.message.reply_text("🚀 Ordenando un redespliegue completo a Railway...\n\nEl bot se apagará en breve y volverá a estar online en unos 2 a 5 minutos.")
    
    # Preparamos la orden (en formato GraphQL) para los servidores de Railway
    url = "https://backboard.railway.app/graphql/v2"
    headers = {
        "Authorization": f"Bearer {RAILWAY_API_TOKEN}",
        "Content-Type": "application/json"
    }
    payload = {
        "query": """
            mutation serviceInstanceRedeploy($environmentId: String!, $serviceId: String!) {
                serviceInstanceRedeploy(environmentId: $environmentId, serviceId: $serviceId)
            }
        """,
        "variables": {
            "environmentId": RAILWAY_ENVIRONMENT_ID,
            "serviceId": RAILWAY_SERVICE_ID
        }
    }
    
    try:
        # Disparamos la orden
        respuesta = requests.post(url, json=payload, headers=headers, timeout=10)
        
        if respuesta.status_code == 200:
            logger.info("✅ Redeploy ejecutado con éxito a través de la API.")
        else:
            await update.message.reply_text(f"⚠️ Railway respondió con un error: {respuesta.text}")
            
    except Exception as e:
        await update.message.reply_text(f"❌ Error de conexión al solicitar el redespliegue: {e}")

# ── Reinicio del bot ───────────────────────────────────────────────────────────

async def cmd_reboot(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Fuerza el reinicio del bot apagando el proceso."""
    if update.effective_user.id not in ADMIN_IDS:
        return

    await update.message.reply_text("🔄 Reiniciando el servidor... Estaré de vuelta en unos 10 a 20 segundos.")
    
    # os._exit(1) fuerza el cierre inmediato de todos los hilos (Flask y Telegram)
    # Al cerrarse con un código de error (1), Railway detecta la caída y lo reinicia al instante.
    os._exit(1)

# ── Construcción de la aplicación ──────────────────────────────────────────────

async def set_commands(app: Application) -> None:
    await app.bot.set_my_commands([
        BotCommand("start",     "Iniciar el bot"),
        BotCommand("status",    "Ver estado de suscripción"),
        BotCommand("subscribe", "Suscribirse – €3/mes"),
        BotCommand("cancel",    "Cancelar suscripción"),
        BotCommand("reset",     "Borrar historial de conversación"),
        BotCommand("help",      "Ayuda"),
    ])


def create_app() -> Application:
    app = Application.builder().token(TELEGRAM_TOKEN).post_init(set_commands).build()

    app.add_handler(CommandHandler("start",                         cmd_start))
    app.add_handler(CommandHandler("status",                        cmd_status))
    app.add_handler(CommandHandler("subscribe",                     cmd_subscribe))
    app.add_handler(CommandHandler("cancel",                        cmd_cancel))
    app.add_handler(CommandHandler("reset",                         cmd_reset))
    app.add_handler(CommandHandler("help",                          cmd_help))
    app.add_handler(CommandHandler("admin",                         cmd_admin))
    app.add_handler(CommandHandler("database",                      cmd_getdb))
    app.add_handler(CommandHandler("block",                         cmd_block))
    app.add_handler(CommandHandler("unblock",                       cmd_unblock))
    app.add_handler(CommandHandler("grant",                         cmd_grant))
    app.add_handler(CommandHandler("reboot -a",                     cmd_redespliege))
    app.add_handler(CommandHandler("reboot",                        cmd_reboot))
    app.add_handler(CallbackQueryHandler(handle_callback))
    app.add_handler(MessageHandler(filters.Document.ALL,            handle_document))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    return app