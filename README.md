# PickASparky API

The backend for [PickASparky](https://www.pickasparky.com), a UK marketplace that matches
homeowners with vetted EV charger installers. One FastAPI service powers the public
website, the Dashboard (installer and team back office) and the homeowner's *My Quotes*
area.

| | |
|---|---|
| **Stack** | Python 3.14 · FastAPI · SQLAlchemy 2 (async) · PostgreSQL · Alembic · Pydantic 2 |
| **Integrations** | SMTP (email) · Cloudinary (images) · Stripe (memberships) · postcodes.io (geocoding) |
| **Packaging** | [uv](https://docs.astral.sh/uv/) · Docker (non-root, health-checked) |

Related apps: the public website (`frontend/`, Next.js) and the Dashboard (`dashboard/`,
React). Each has its own README.

## What it does

- **Quote requests.** A homeowner's request is geocoded, matched to every eligible installer
  whose coverage includes the address, and emailed to them. Only the first
  `max installers` (a Setting, default 5) to respond may quote. The team can switch
  automatic matching off to choose installers by hand.
- **Installers.** Profiles, plans (Free, Pro, Premium; prices and rules are edited in the
  Dashboard and mirrored to Stripe), accreditations, galleries, reviews, claimed and
  unclaimed directory listings.
- **Conversations and offers** between homeowners and installers, with private email links
  for homeowners (no account or password needed).
- **Back office.** Roles and permissions, website content, blog, locations and SEO, reviews,
  contact inbox, platform settings.

## Quick start

You need Python 3.14, [uv](https://docs.astral.sh/uv/) and a PostgreSQL database.

```bash
uv sync                                   # install dependencies into .venv

cat > .env <<'EOF'                        # minimal development configuration
ENVIRONMENT=development
SECRET_KEY=change-me-development-only
DATABASE_URL=postgresql+asyncpg://pickasparky:pickasparky@127.0.0.1:5432/pickasparky
FRONTEND_URL=http://localhost:3000
DASHBOARD_URL=http://localhost:5173
CORS_ORIGINS=http://localhost:3000,http://localhost:5173
EOF

uv run alembic upgrade head               # create / update the schema
uv run python -m app.cli seed-locations   # reference data (towns and regions)
uv run python -m app.cli seed-content     # the 193 installer listings (plus sample blog posts and showcase profiles in development)
uv run python -m app.cli seed-admin       # the administrator named by ADMIN_EMAIL and ADMIN_PASSWORD
uv run uvicorn app.main:app --reload      # http://localhost:8000
```

- Interactive API docs: <http://localhost:8000/docs> (off in production unless `DOCS_ENABLED=true`).
- Liveness: `GET /health`. Readiness (checks the database): `GET /health/ready`.
- API root: `/api/v1`.
- Sign-in to the Dashboard: the administrator from `ADMIN_EMAIL` / `ADMIN_PASSWORD` (see
  [What a new database contains](#what-a-new-database-contains)). There are no demo logins.

Without SMTP settings no email leaves the server; check `uv run python -m app.cli test-email you@example.com`
once SMTP is configured.

## Configuration

Settings are read from the environment (and a local `.env`). `app/core/config.py` is the
reference; invalid or missing values stop the app at start-up with a clear message.
A blank value (`KEY=`) means "not set".

| Variable | Required | Purpose |
|---|---|---|
| `ENVIRONMENT` | | `development` (default), `production` or `test` |
| `SECRET_KEY` | yes | Signs tokens. At least 32 characters in production (`openssl rand -hex 32`) |
| `DATABASE_URL` | yes | PostgreSQL URL. `postgres://` and `postgresql://` are accepted and use the async driver |
| `INTERNAL_API_KEY` | production | Shared secret with the website so it can pass visitors' real IPs (rate limits) and trigger cache refreshes |
| `FRONTEND_URL` | | Public website URL (links in emails, CORS) |
| `FRONTEND_INTERNAL_URL` | | How the API reaches the website privately (e.g. `http://frontend:3000`); defaults to `FRONTEND_URL` |
| `DASHBOARD_URL` | | Public Dashboard URL (links in emails) |
| `CORS_ORIGINS` | | Comma-separated allowed origins (website and Dashboard) |
| `ALLOWED_HOSTS` | | Comma-separated hostnames the API answers to; `*` is for development only |
| `DOCS_ENABLED` | | Force the API docs on or off (default: on except in production) |
| `SESSION_COOKIE_SAMESITE`, `SESSION_COOKIE_DOMAIN` | | Dashboard refresh-cookie scope. Keep the Dashboard and API on the same site and leave `lax` |
| `ACCESS_TOKEN_EXPIRE_MINUTES`, `REFRESH_TOKEN_EXPIRE_DAYS` | | Session lifetimes (15 minutes, 30 days) |
| `MAGIC_LINK_EXPIRE_MINUTES`, `CUSTOMER_SESSION_IDLE_DAYS`, `CUSTOMER_SESSION_MAX_DAYS` | | Homeowner email-link lifetime and session limits |
| `SMTP_HOST`, `SMTP_PORT`, `SMTP_USERNAME`, `SMTP_PASSWORD`, `SMTP_START_TLS`, `SMTP_USE_TLS` | for email | Port 587 with `SMTP_START_TLS=true`, or port 465 with `SMTP_USE_TLS=true` and `SMTP_START_TLS=false` |
| `EMAIL_FROM`, `EMAIL_FROM_NAME`, `SUPPORT_EMAIL` | | Sender and the team's address (alerts are sent here) |
| `CLOUDINARY_CLOUD_NAME`, `CLOUDINARY_API_KEY`, `CLOUDINARY_API_SECRET`, `CLOUDINARY_FOLDER` | for uploads | Installer logos, gallery photos and location images |
| `STRIPE_SECRET_KEY`, `STRIPE_WEBHOOK_SECRET` | for payments | Plans and prices live in the database and are mirrored to Stripe: no price ids are configured |
| `RATE_LIMIT_STORAGE_URI` | | `memory://` for one instance; `redis://host:6379` when running several |
| `POSTCODES_API_URL` | | Geocoding service (default `https://api.postcodes.io`) |
| `MAX_QUOTE_MATCHES` | | Default for how many installers may respond to a request (1 to 20, default 5; editable in Settings) |
| `QUOTE_RECOVERY_INTERVAL_SECONDS`, `QUOTE_RECOVERY_BATCH` | | How often (60) and how many (25) waiting requests are retried when the geocoder was down |
| `ADMIN_EMAIL`, `ADMIN_PASSWORD` | first start | The one administrator, created on start-up if that email has no account. An existing account is never changed, so remove `ADMIN_PASSWORD` after the first start. The password needs 10 to 128 characters with a letter and a digit |

## What a new database contains

On every start (`docker-entrypoint.sh`) the API applies the migrations and then runs
`seed-locations`, `seed-content` and `seed-admin`. All three are safe to repeat. A production
database ends up with exactly this and nothing else:

| Data | Source | Notes |
|---|---|---|
| 34 locations | `app/data/locations.json` | Towns, regions and the directory layout; always follows the file |
| 193 installers | `app/data/listings.json` (the client's `EV_installers.xlsx`, rows marked *Valid*) | Approved, public, unclaimed listings on the Free plan; a business claims its profile through its email address. Applied once (batch `directory-listings-2026-10`), so later edits or deletions are kept |
| 1 administrator | `ADMIN_EMAIL`, `ADMIN_PASSWORD` | Verified, role *owner*. Created only when no account with that email exists |
| Plans | migration `0011` | The default plan catalogue, edited afterwards in the Dashboard |

Outside production `seed-content` also adds six sample blog articles and the showcase profiles
with sample reviews (`app/data/blog.json`, `app/data/demo.json`) so the website can be built with
content; they are refused when `ENVIRONMENT=production`. There are no demo accounts anywhere.

## When the postcode service is down

postcodes.io is an external service. If it cannot answer when a homeowner submits a request:

1. The request is **stored in full** with the status `pending_location` (never "unmatched").
2. The homeowner sees and receives exactly what they always do: the usual confirmation email,
   the usual success page, and the request under *My Quotes* as "matching". Nothing reveals
   the outage.
3. The **team** gets an email (`quote_awaiting_location`), and the request shows under
   *Leads & Quotes › Waiting for you* so installers can be chosen by hand straight away.
4. Every worker retries about once a minute (`app/services/quote_recovery.py`). As soon as the
   service answers, the request is matched and the installers are emailed exactly as for a
   normal request, including held requests and requests sent to one chosen installer. A
   mistyped postcode becomes `unmatched` and the team is told why.

Requests are claimed with `FOR UPDATE SKIP LOCKED`, so several workers or replicas never
process the same request twice, and a request the team has already shared is left alone.
Geocoding sits behind the `Geocoder` interface (`app/services/geocoding.py`), so another
provider or country can be added without touching the matching code.

## Everyday commands

```bash
uv run alembic upgrade head                    # apply migrations
uv run alembic revision -m "describe change"   # new migration
uv run pytest                                  # tests (needs PostgreSQL, see below)
uv run ruff check . && uv run ruff format --check .
```

Operational commands: `uv run python -m app.cli --help`

| Command | Purpose |
|---|---|
| `seed-locations` | Upsert towns and regions (safe to repeat) |
| `seed-content` | Add content batches not added yet: the directory listings (and, outside production, sample blog articles and showcase installers) |
| `seed-admin` | Create the administrator from `ADMIN_EMAIL` / `ADMIN_PASSWORD` unless it exists; never changes an existing account |
| `create-admin` | Create a verified admin account by hand (prompts for email and password) |
| `test-email <to>` | Send one test email and print the exact SMTP error, if any |
| `location-image <slug> <file>` | Upload a photo for a location page |
| `migrate-media` | Upload bundled website images to Cloudinary |

## Tests and quality

The suite runs against a real PostgreSQL database, `pickasparky_test` by default
(`postgresql+asyncpg://pickasparky:pickasparky@127.0.0.1:5432/pickasparky_test`; override with
`TEST_DATABASE_URL`). External services (SMTP, Stripe, geocoding, Cloudinary) are replaced by
fakes. Create the database and role once, then run `uv run pytest`.

Code style is enforced with Ruff (`pyproject.toml`).

## Project layout

```
app/
  main.py            application factory, middleware, background jobs
  cli.py             operational commands
  api/               dependencies and routers (`api/v1/endpoints/*`)
  core/              settings, database, security, enums, errors
  models/            SQLAlchemy models
  schemas/           request and response models
  services/          business logic (matching, quotes, billing, email, ...)
  templates/email/   HTML and text email templates
  data/, content/    seed data and default website copy
alembic/             migrations
tests/               pytest suite
```

## Deploying

The image (`Dockerfile`) is multi-stage, runs as a non-root user and has a health check.
`docker-entrypoint.sh` applies migrations, seeds reference data and starts uvicorn with
`WEB_CONCURRENCY` workers (default 2) behind the platform's reverse proxy (Coolify/Traefik).

Checklist for production:

- `ENVIRONMENT=production`, a strong `SECRET_KEY`, `INTERNAL_API_KEY` set to the same value as
  on the website, `ALLOWED_HOSTS` and `CORS_ORIGINS` set to the real domains.
- A managed PostgreSQL database with backups; `DATABASE_URL` pointing at it.
- SMTP, Cloudinary and Stripe credentials; the Stripe webhook pointing at the API.
- `RATE_LIMIT_STORAGE_URI=redis://...` if more than one replica runs.
- Dashboard and API on the same site (for example `dashboard.` and `api.` under one domain).
- Never commit `.env` or any secret.

## Security notes

- Passwords use Argon2; access tokens last 15 minutes; refresh tokens live in an httpOnly cookie
  scoped to the session endpoint and cannot be read by JavaScript.
- Session endpoints require `X-Requested-With`, and CORS only admits the configured origins.
- Public forms are rate limited per visitor IP; a honeypot field quietly discards bots.
- New-lead emails to installers carry the homeowner's first name only: no surname, phone
  number or email address.
- Security headers are set on every response; authentication responses are never cached.
