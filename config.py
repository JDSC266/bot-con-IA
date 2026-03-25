#config.py - Configuración central del bot
import os
from dotenv import load_dotenv

load_dotenv()

# ── Telegram ──────────────────────────────────────────────────────────────────
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "")

# ── Groq AI ───────────────────────────────────────────────────────────────────
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
MAX_TOKENS   = int(os.getenv("MAX_TOKENS", "1024"))

# ── PayPal ────────────────────────────────────────────────────────────────────
PAYPAL_CLIENT_ID     = os.getenv("PAYPAL_CLIENT_ID", "")
PAYPAL_CLIENT_SECRET = os.getenv("PAYPAL_CLIENT_SECRET", "")
PAYPAL_MODE          = os.getenv("PAYPAL_MODE", "sandbox")
PAYPAL_PLAN_ID       = os.getenv("PAYPAL_PLAN_ID", "")

# ── App / Railway ─────────────────────────────────────────────────────────────
WEBHOOK_URL      = os.getenv("WEBHOOK_URL", "")
PORT             = int(os.getenv("PORT", "8080"))
DATABASE_PATH    = os.getenv("DATABASE_PATH", "bot_database.db")
RAILWAY_WEBHOOK  = os.getenv("RAILWAY_WEBHOOK", "")

# ── Suscripción ───────────────────────────────────────────────────────────────
TRIAL_DAYS            = 30
SUBSCRIPTION_PRICE    = 3.00
SUBSCRIPTION_CURRENCY = "EUR"

# ── Administradores ───────────────────────────────────────────────────────────
ADMIN_IDS = [
    int(x.strip())
    for x in os.getenv("ADMIN_IDS", "").split(",")
    if x.strip().isdigit()
]

# ── API de Railway para Redeploy ──────────────────────────────────────────────
RAILWAY_API_TOKEN = os.getenv("RAILWAY_API_TOKEN")
# Estas dos variables Railway las inyecta automáticamente por nosotros:
RAILWAY_ENVIRONMENT_ID = os.getenv("RAILWAY_ENVIRONMENT_ID")
RAILWAY_SERVICE_ID = os.getenv("RAILWAY_SERVICE_ID")

# ── Personalidad del asistente ────────────────────────────────────────────────
SYSTEM_PROMPT = """Eres un asistente de IA amable, inteligente y conversacional. \
Tienes una personalidad cálida y puedes ayudar con una gran variedad de tareas: \
responder preguntas, escribir textos, analizar información, dar consejos, \
ayudar con código, traducir, hacer resúmenes y mucho más.

Hablas de manera natural y adaptable — puedes ser formal o informal según el \
contexto. Recuerdas el hilo de la conversación actual y las referencias cuando \
es útil. Cuando no sabes algo, lo admites con honestidad. Cuando das opiniones, \
las presentas como tuyas y no como verdades absolutas.

Responde siempre en el mismo idioma que use el usuario.\

Responde al grano, no te extiendas mucho, y nunca mientas, si no sabes algo, \
simplemente di que no sabes, y ya, no hay problema si no sabes algo."""