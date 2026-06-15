# Plan de comercialización (Fase 2) — listo para cuando llegue el momento

> Documento de diseño. **No construido todavía** (a propósito): primero validar
> con canales propios (Fase 1). Esto queda listo para ejecutar cuando el dueño
> decida lanzar la venta. Hosting previsto: **Hetzner** (infra propia). Modelo:
> **suscripción mensual**, software profesional e independiente.

## Fases

- **Fase 1 (ahora):** usar PressForge para los canales propios (*Curiosidades
  Mitológicas*, etc.), hacerlos caso de éxito y generar los tutoriales con la
  propia app. NO se vende ni se reparte aún. La **licencia offline + login**
  actuales bastan como base.
- **Fase 2 (al lanzar):** landing + venta por **suscripción mensual** con
  control de acceso (1 mes; si no paga, se revoca hasta que pague).

## Arquitectura de Fase 2 (cuando se construya)

Componente nuevo y separado: **PressForge License Server** (en Hetzner, dominio propio).

```
Cliente ─▶ Landing/registro ─▶ Stripe (cobro mensual) ─▶ webhook ─▶ License Server
                                                                      │
   App PressForge (en su PC) ──(valida online cada X)──▶ /api/validate ┘
        · suscripción activa  → funciona (con periodo de gracia offline, ej. 3-7 días)
        · suscripción vencida → se bloquea hasta pagar
```

**Piezas:**
1. **License Server** (FastAPI + base de datos: SQLite o Postgres en Hetzner):
   - Tablas: `users`, `subscriptions` (estado, plan, vence_el, stripe_ids), `licenses`/`devices`.
   - **Stripe** (procesador de pagos — único "tercero", estándar de la industria; el dueño sigue siendo dueño de clientes/datos/licencias):
     - Checkout de suscripción mensual.
     - **Webhooks**: `invoice.paid` → activa/renueva; `customer.subscription.deleted`/`invoice.payment_failed` → revoca.
   - **API de validación** que la app consulta: `POST /api/validate {license, device}` → `{active, plan, expires}`.
   - **Descarga protegida** del instalador solo para suscriptores activos.
2. **Panel de administración** (web, para el dueño): ver usuarios, estado, activar/desactivar manualmente, métricas.
3. **Portal del cliente**: registro, gestionar su suscripción/tarjeta (Stripe Customer Portal evita construir esto), descargar el software.
4. **Cambio en la app PressForge:**
   - La activación pide **email + clave de licencia/cuenta** y valida **online** contra el server.
   - Guarda un token + **periodo de gracia offline** (sigue funcionando sin internet unos días; al expirar, exige revalidar).
   - Reemplaza la verificación offline Ed25519 actual (que queda como mecanismo de firma del token que emite el server).

## Lo que hará falta (al construir Fase 2)
- Cuenta **Stripe** (gratis; ~2.9% + €0.30 por cobro, sin cuota fija). Recurrente nativo + Customer Portal.
- **Servidor Hetzner** (ya disponible) + **dominio** + HTTPS (Caddy/Nginx + Let's Encrypt).
- Decidir **planes y precios** (ej. único plan mensual, o Básico/Pro con límites).
- **Landing page** (puede ser estática + checkout de Stripe).
- (Opcional) **Instalador nativo** (PyInstaller) para que el cliente no use git/terminal.

## Decisiones pendientes (cuando toque)
- ¿Un plan o varios? ¿Límites por plan (nº de marcas, reels/mes)? → define si la licencia/token lleva "plan" y si la app aplica cuotas.
- ¿Prueba gratis (trial de Stripe)? ¿Mensual y anual?
- ¿Se vende junto a un curso/academia? (podría ser otra membresía o incluido).
- ¿1 licencia = 1 dispositivo? (registro de `device` para limitar).

## Cómo evoluciona lo ya construido
- `licensing.py` (Ed25519 offline) → pasa a **verificar el token firmado que emite el server** (mismo mecanismo de firma, ahora con expiración corta + revalidación online).
- `auth.py` (login local) → se mantiene (contraseña local del equipo) **o** se integra con la cuenta del cliente del server.
- BYOK (Ajustes → API Keys) → **sigue igual**: cada cliente pone su propia key de OpenAI (paga su consumo). La suscripción es por el **software**, no por la IA.

## Estimación
Construir Fase 2 (server + Stripe + panel + cambio de validación en la app + deploy en Hetzner) ≈ **1-2 semanas** de trabajo enfocado. Hacerlo **cuando haya intención real de lanzar**, no antes.
