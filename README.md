# Reservared

Agenda en línea para centros con varios profesionales y sucursales: los
pacientes reservan (y pagan) solos, y el equipo trabaja en un panel por
módulos, cada uno con su permiso.

## Módulos del panel

| Módulo | Qué hace |
|---|---|
| **Dashboard** | Citas, asistencia, cancelaciones (quién, con cuánta anticipación, motivo), inasistencias, ocupación, cobrado y por cobrar. Filtra por periodo, profesional, sucursal y tipo de servicio. |
| **Agendar** | Horas libres por servicio, modalidad, sucursal, especialidad y profesional. Agenda a un paciente existente (buscador) o nuevo. Permite sobrecupos. |
| **Agenda** | Vista semanal y vista del día con una columna por profesional. Arrastrando una cita se mueve (reagenda) o se copia. |
| **Citas** | Listado con filtros y ficha de cada cita: estado, reagendar, copiar (también varias semanas seguidas), cancelar con motivo, pagos, sesión online, WhatsApp, nota interna y nota de la sesión. |
| **Pacientes** | Ficha: datos, previsión, contacto de emergencia, historial de citas y pagos. **Ficha clínica** aparte (motivo de consulta, antecedentes y evolución por sesión), sólo con ese permiso. |
| **Cobranza** | Lo que se debe, abonos, pagos por medio (efectivo, transferencia, tarjeta, Webpay, Mercado Pago), recordatorios de pago con enlace, resumen por profesional y descarga CSV. |
| **Profesionales** | Perfil, especialidades, servicios y horario por tramo: presencial, online o ambos, y en qué sucursal. |
| **Cuentas y permisos** | Cuentas del equipo con perfiles (Administración, Recepción, Profesional) y permisos por módulo. |
| **Configuración** | Servicios por tipo, con precio base y **precios especiales** por modalidad, especialidad, profesional o sucursal. También sucursales, bloqueos, reglas de reserva, pagos, avisos y Google. |

Una cuenta de profesional ve sólo su agenda, sus pacientes y sus números, salvo
que tenga el permiso "Todo el equipo". La ficha clínica la ve sólo quien tenga
ese permiso, ni siquiera la administración por defecto.

## Lo que ve el paciente

- **Página de reservas** (`/reservar`): dónde (sucursal u online) → servicio
  (agrupado por tipo) → profesional (con filtro por especialidad) → día y hora
  → datos y pago. Se puede poner dentro de WordPress.
- **Página de su cita** (`/cita/…`): ve la hora y el lugar, entra a la sesión
  online, paga el saldo o cancela indicando el motivo.
- **Avisos**: confirmación y recordatorio del día antes, por correo y por
  WhatsApp. Avisos de reagendamiento y cancelación.

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
| `WEBPAY_CODIGO_COMERCIO` / `WEBPAY_LLAVE_SECRETA` | Webpay Plus de Transbank (opcional). Para probar sin contrato: `WEBPAY_AMBIENTE=integracion` |
| `WHATSAPP_TOKEN` / `WHATSAPP_NUMERO_ID` | WhatsApp Business de Meta (opcional) |
| `CLAVE_TAREAS` | Un texto al azar: protege la tarea de recordatorios |

### 4. Primer ingreso

Entra a `https://…/panel` con `ADMIN_EMAIL` y `ADMIN_CLAVE`. Luego:

1. **Sucursales**: crea las tuyas. Si atiendes en un solo lugar, sáltate este paso.
2. **Servicios y precios**: crea los servicios con su tipo, por ejemplo
   Psicología o Nutrición, y su modalidad (presencial, online o ambas). Agrega
   los precios especiales que necesites.
3. **Profesionales**: crea las especialidades y a cada profesional con su
   horario por tramo. Marca *Puede entrar al panel* y le llega un correo para
   elegir su contraseña.
4. **Cuentas y permisos**: crea la cuenta de recepción y ajusta los permisos.
5. **Ajustes**: revisa las reglas de reserva y los pagos, y copia la dirección
   de tu página de reservas o el código para WordPress.

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

## Webpay (Transbank)

1. Contrata **Webpay Plus** con Transbank (modalidad REST). Te entregan un
   código de comercio y una llave secreta.
2. Ponlos en `WEBPAY_CODIGO_COMERCIO` y `WEBPAY_LLAVE_SECRETA`.
3. En el panel, **Ajustes → Pago en línea**, marca Webpay.

Para probar antes de tener contrato, pon `WEBPAY_AMBIENTE=integracion`. Así se
usa el ambiente de pruebas de Transbank con sus tarjetas de prueba, sin cobrar
de verdad. Sin código de comercio y sin ese ajuste, Webpay queda apagado: nunca
cae en modo de pruebas por olvido.

## WhatsApp

Hay dos formas:

- **Sin configurar nada**: en cada cita hay botones que abren WhatsApp (en el
  teléfono o en WhatsApp Web) con el mensaje ya escrito: la hora, o el cobro del
  saldo. Lo envías tú.
- **Automático** (confirmación y recordatorio), con la API de WhatsApp Business
  de Meta:
  1. En [Meta for Developers](https://developers.facebook.com/) crea una app de
     tipo *Business* y agrega WhatsApp. Necesitas un número que no esté usando
     la app normal de WhatsApp.
  2. Crea dos **plantillas** de mensaje, categoría *Utilidad*, idioma español.
     Las dos llevan cuatro datos, en este orden: nombre, fecha y hora,
     profesional y enlace.
     - `confirmacion_hora`: *Hola {{1}}, tu hora quedó reservada para el {{2}}
       con {{3}}. Para ver o cancelar tu hora: {{4}}*
     - `recordatorio_hora`: *Hola {{1}}, te recordamos tu hora del {{2}} con
       {{3}}. Si no puedes asistir, cancela aquí: {{4}}*
  3. Cuando Meta las apruebe, pon `WHATSAPP_TOKEN` (un token permanente de
     usuario del sistema) y `WHATSAPP_NUMERO_ID`.

Meta cobra por cada conversación que inicia la empresa (unos pocos pesos).

## Recordatorio del día antes

La tarea `/tareas/recordatorios?clave=CLAVE_TAREAS` envía el recordatorio, por
correo y WhatsApp, de las citas de las próximas 24 horas que todavía no lo
tienen. Hay que llamarla una vez por hora. Dos opciones:

- **Render → New → Cron Job**: comando
  `curl -fsS -X POST "https://TU-DIRECCION/tareas/recordatorios?clave=TU_CLAVE"`
  y horario `0 * * * *`.
- **GitHub Actions**: un flujo con `schedule: - cron: "0 * * * *"` que haga el
  mismo `curl`.

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
