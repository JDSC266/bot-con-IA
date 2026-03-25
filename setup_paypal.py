"""
setup_paypal.py — Crea el Producto y el Plan de suscripción en PayPal.

Ejecuta este script UNA SOLA VEZ antes de desplegar el bot.
Copia el Plan ID resultante y añádelo a tu .env como PAYPAL_PLAN_ID.

Uso:
    python setup_paypal.py
"""
import os
import sys
from dotenv import load_dotenv

load_dotenv()

# Verificación previa de credenciales
if not os.getenv("PAYPAL_CLIENT_ID") or not os.getenv("PAYPAL_CLIENT_SECRET"):
    print("❌ ERROR: Debes configurar PAYPAL_CLIENT_ID y PAYPAL_CLIENT_SECRET en tu .env")
    sys.exit(1)

import paypal_handler

def main():
    print("=" * 55)
    print("  Configuración inicial de PayPal — Asistente IA Bot")
    print("=" * 55)
    mode = os.getenv("PAYPAL_MODE", "live")
    print(f"\n  Modo: {mode.upper()}")
    print(f"  Precio: €{os.getenv('SUBSCRIPTION_PRICE', '3.00')}/mes")
    print()

    try:
        plan = paypal_handler.create_plan_and_product()
        plan_id = plan["id"]

        print("✅ ¡Plan creado correctamente!\n")
        print(f"  Plan ID : {plan_id}")
        print(f"  Estado  : {plan.get('status', 'N/A')}\n")
        print("=" * 55)
        print("  Añade esta línea a tu .env (o variable de Railway):")
        print(f"\n  PAYPAL_PLAN_ID={plan_id}\n")
        print("=" * 55)

    except Exception as e:
        print(f"\n❌ Error al crear el plan: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()