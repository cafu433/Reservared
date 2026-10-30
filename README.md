# Reservared

Agenda en línea para centros con varios profesionales: los pacientes reservan
(y pagan) solos, y cada profesional entra a ver y manejar su propia agenda.

- **Página de reservas** (`/reservar`): servicio → profesional (o "cualquiera") →
  día y hora → datos. Valida el RUT. Se puede poner dentro de WordPress.
- **Página de la cita** (`/cita/…`): el paciente ve su hora, entra a la sesión
  online, paga o cancela.
- **Panel** (`/panel`):
  - Agenda semanal de todo el equipo o de un profesional.
  - Citas, pacientes con su historial y notas internas.
  - Bloqueos (vacaciones, feriados).
  - Para la administración: profesionales con su horario, sus servicios y su
    acceso; servicios; equipo; ajustes.
- **Mercado Pago**: cobro opcional u obligatorio, total o abono. Si el pago no
  llega a tiempo, la hora se libera.
- **Google Meet**: cada cita de un servicio online crea su evento en Google
  Calendar con enlace de Meet. Sin Google, se usa la sala fija del profesional.
- **Correos**: confirmación al paciente; aviso al negocio y al profesional;
  cambios de estado; recuperación de contraseña.

Hecha con Flask, SQLAlchemy y PostgreSQL, igual que el sistema de Almex.

## Poner en marcha en Render

### 1. Base de datos

Crea una base PostgreSQL gratis en [Neon](https://neon.tech) (o en Render, pagada) y
copia su dirección de conexión. En Neon usa la conexión **directa**, no la que
dice `-pooler`: el pooler corta las migraciones.

### 2. Servicio web

En tu proyecto de Render: **Create new service → Web Service** → elige este
repositorio. Completa:

| Campo | Valor |
|---|---|
| Runtime | Python |
| Build Command | `pip install -r requirements.txt && flask db upgrade` |
| Start Command | `gunicorn wsgi:app --workers 2 --threads 8 --preload --timeout 60 --bind 0.0.0.0:$PORT` |
| Health Check Path | `/healthz` |
| Plan | **Starter**. El gratis se duerme y la página de reservas tarda ~1 minuto en abrir. |

### 3. Variables de entorno (Render → Environment)

| Variable | Qué poner |
|---|---|
| `FLASK_APP` | `wsgi.py` |
| `FLASK_ENV` | `production` |
| `PYTHON_VERSION` | `3.12.4` |
| `SECRET_KEY` | Un texto largo al azar (Render lo genera con "Generate") |
| `DATABASE_URL` | La dirección de Neon |
| `NOMBRE_NEGOCIO` | Como aparece ante los pacientes, por ejemplo `Centro Psicológico Alameda` |
| `URL_PUBLICA` | La dirección del servicio, por ejemplo `https://reservared.onrender.com` (sin `/` al final) |
| `ADMIN_EMAIL` / `ADMIN_CLAVE` | Tu cuenta de administración. Se crea sola la primera vez que arranca; después cambia la clave en el panel. |
| `SMTP_HOST`, `SMTP_PUERTO`, `SMTP_USUARIO`, `SMTP_CLAVE`, `CORREO_REMITENTE` | Datos del correo saliente (ver abajo) |
| `MP_ACCESS_TOKEN` | Access Token de Mercado Pago (opcional) |
| `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` | Para Google Meet (opcional) |

### 4. Primer ingreso

Entra a `https://…/panel` con `ADMIN_EMAIL` y `ADMIN_CLAVE`. Luego:

1. **Servicios**: crea los tuyos. Marca *Online* los que sean por videollamada.
2. **Profesionales**: crea a cada uno con su horario. Marca *Puede entrar al
   panel* y le llega un correo para elegir su contraseña.
3. **Ajustes**: revisa las reglas de reserva y copia la dirección de tu página de
   reservas o el código para WordPress.

## Correo saliente

Cualquier servicio SMTP sirve. Algunas opciones:

- **Brevo** (gratis hasta 300 correos al día): `smtp-relay.brevo.com`, puerto `587`.
- **Gmail o Google Workspace**: `smtp.gmail.com`, puerto `587`, con una
  [contraseña de aplicación](https://myaccount.google.com/apppasswords).

Sin SMTP la aplicación funciona igual, pero no envía correos.

## Mercado Pago

1. En [Mercado Pago Developers → Tus integraciones](https://www.mercadopago.cl/developers/panel/app)
   crea una aplicación de tipo *Checkout Pro*.
2. Copia el **Access Token** a `MP_ACCESS_TOKEN`. Para probar sin cobrar de
   verdad, usa primero el de prueba.
3. En el panel, **Ajustes → Pago en línea**, elige opcional u obligatorio.

Una cita se marca pagada sólo después de consultar el pago a Mercado Pago.

## Google Meet

1. En [Google Cloud Console](https://console.cloud.google.com/) crea un proyecto
   y activa la **Google Calendar API**.
2. Configura la *pantalla de consentimiento OAuth*, de tipo externa, y agrega tu
   correo como usuario de prueba.
3. **Credenciales → Crear credenciales → ID de cliente de OAuth**, de tipo
   *Aplicación web*. En *URI de redireccionamiento autorizados* pon
   `https://TU-DIRECCION/panel/google/volver`.
4. Copia el ID y el secreto a `GOOGLE_CLIENT_ID` y `GOOGLE_CLIENT_SECRET`.
5. En el panel, **Ajustes → Conectar con Google**, con la cuenta de Google del
   negocio.

Cada cita online crea un evento en ese calendario con su Meet, e invita al
paciente y al profesional. Si se cancela la cita, se borra el evento.

## En WordPress

En **Ajustes** del panel está el código listo para copiar. Va en un bloque
*HTML personalizado* y muestra la agenda dentro de tu página, ajustando su
alto sola.

## Desarrollo

```bash
python -m venv venv && source venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env        # y completa
flask db upgrade
flask run
pytest
```

Para cambiar la base de datos: modifica `app/models.py`, corre
`flask db migrate -m "qué cambió"`, revisa el archivo nuevo en
`migrations/versions/` y súbelo junto con el cambio.
