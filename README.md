# 🤖 Asistente IA Bot — Telegram

Bot de Telegram con inteligencia artificial (Claude), prueba gratuita de 30 días y suscripción mensual de **€3/mes** vía PayPal. Listo para desplegar en **Railway**.

---

## 📁 Estructura del proyecto

```
telegram-ai-bot/
├── main.py              ← Punto de entrada (Flask + Bot Telegram)
├── bot.py               ← Handlers y comandos de Telegram
├── database.py          ← Gestión de usuarios y suscripciones (SQLite)
├── claude_api.py        ← Integración con la API de Claude
├── paypal_handler.py    ← Integración con la API de PayPal
├── config.py            ← Configuración central
├── setup_paypal.py      ← Script único para crear el plan en PayPal
├── requirements.txt     ← Dependencias Python
├── Procfile             ← Comando de inicio para Railway
├── railway.toml         ← Configuración de Railway
├── .env                 ← Variables de entorno (¡no subir a Git!)
└── .gitignore
```

---

## 🚀 Guía de despliegue en Railway

### Paso 1 — Cuenta PayPal Developer

1. Ve a [developer.paypal.com](https://developer.paypal.com/dashboard/applications/live)
2. Crea una **Live App** y copia el `Client ID` y `Client Secret`
3. Añádelos al archivo `.env`

### Paso 2 — Crear el plan de suscripción PayPal

Ejecuta este script **una sola vez** en tu máquina local:

```bash
pip install -r requirements.txt
python setup_paypal.py
```

Copia el **Plan ID** que aparece y añádelo al `.env` como `PAYPAL_PLAN_ID`.

### Paso 3 — Desplegar en Railway

1. Crea una cuenta en [railway.app](https://railway.app)
2. Haz clic en **New Project → Deploy from GitHub Repo**
   *(o usa el CLI: `railway init && railway up`)*
3. En la sección **Variables**, añade todas las variables de tu `.env`
4. Railway te dará una URL pública (ej. `https://mi-bot.up.railway.app`)
   → Cópiala y añádela como `WEBHOOK_URL` en las variables de Railway

### Paso 4 — Configurar el webhook de PayPal

1. En tu app de PayPal Developer → **Webhooks → Add Webhook**
2. URL del webhook: `https://TU-APP.up.railway.app/paypal/webhook`
3. Selecciona estos eventos:
   - `BILLING.SUBSCRIPTION.ACTIVATED`
   - `BILLING.SUBSCRIPTION.CANCELLED`
   - `BILLING.SUBSCRIPTION.SUSPENDED`
   - `PAYMENT.SALE.COMPLETED`

---

## ⚙️ Variables de entorno requeridas

| Variable               | Descripción                                     |
|------------------------|-------------------------------------------------|
| `TELEGRAM_TOKEN`       | Token de tu bot (obtenido de @BotFather)        |
| `CLAUDE_API_KEY`       | Clave API de Anthropic                          |
| `PAYPAL_CLIENT_ID`     | Client ID de tu app PayPal Live                 |
| `PAYPAL_CLIENT_SECRET` | Client Secret de tu app PayPal Live             |
| `PAYPAL_MODE`          | `live` (producción) o `sandbox` (pruebas)       |
| `PAYPAL_PLAN_ID`       | ID del plan generado con `setup_paypal.py`      |
| `WEBHOOK_URL`          | URL pública de Railway (sin barra al final)     |
| `ADMIN_IDS`            | Tu user_id de Telegram (usa @userinfobot)       |

---

## 💬 Comandos del bot

| Comando      | Descripción                            |
|--------------|----------------------------------------|
| `/start`     | Registrarse y ver bienvenida           |
| `/status`    | Ver estado de prueba / suscripción     |
| `/subscribe` | Obtener enlace de pago PayPal          |
| `/cancel`    | Cancelar suscripción activa            |
| `/reset`     | Borrar historial de conversación       |
| `/help`      | Mostrar ayuda                          |

### Comandos de administración (solo para ADMIN_IDS)

| Comando                  | Descripción                          |
|--------------------------|--------------------------------------|
| `/admin`                 | Ver estadísticas de usuarios         |
| `/block <user_id>`       | Bloquear un usuario                  |
| `/unblock <user_id>`     | Desbloquear un usuario               |
| `/grant <user_id> <días>`| Dar días de suscripción gratuita     |

---

## 🔄 Flujo de suscripción

```
Usuario /subscribe
      │
      ▼
Bot genera enlace PayPal ──► Usuario aprueba el pago
                                        │
                                        ▼
                           PayPal envía webhook al bot
                                        │
                                        ▼
                        Bot activa suscripción en DB
                                        │
                                        ▼
                        Bot notifica al usuario en Telegram ✅
```

---

## 📦 Prueba local

```bash
# 1. Instalar dependencias
pip install -r requirements.txt

# 2. Configurar .env (ya viene pre-configurado con tus claves)
# Solo añade PAYPAL_* y WEBHOOK_URL

# 3. Ejecutar
python main.py
```

---

## ⚠️ Notas importantes

- **Base de datos**: SQLite funciona en Railway, pero el archivo se resetea con cada redeploy. Para producción permanente, añade un servicio **PostgreSQL** en Railway y conecta con `DATABASE_URL`.
- **Seguridad**: Nunca subas el archivo `.env` a GitHub. Ya está en `.gitignore`.
- **PayPal Sandbox**: Para pruebas usa `PAYPAL_MODE=sandbox` y cuentas de prueba de PayPal Developer.