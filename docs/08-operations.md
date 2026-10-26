# 8 Operations

## 8.1 Requirements

- Docker Engine 24+ with Compose v2 (Linux server, Windows/macOS with Docker Desktop)
- 2 vCPU, 2–4 GB RAM, disk for database and files (typical SME: < 20 GB)
- A reverse proxy with TLS for production (Traefik, nginx, Caddy, IIS/ARR, Azure App Gateway)
- On Azure, the managed alternative to Docker Compose: [18 Azure Container Apps](18-azure-container-apps.md)

## 8.2 Install

```bash
git clone <repo> almlight && cd almlight
cp .env.example .env        # set POSTGRES_PASSWORD and ALMLIGHT_ADMIN_PASSWORD
docker compose up -d --build
# open http://<host>:48080 and sign in as "admin"
```

If `ALMLIGHT_ADMIN_PASSWORD` is empty, a password is generated once and printed in the log:
`docker compose logs app | grep administrator`.

## 8.3 Configuration (environment variables)

| Variable | Default | Purpose |
|---|---|---|
| `ALMLIGHT_PORT` | `48080` | Host port (compose) |
| `POSTGRES_PASSWORD` | `almlight` | Database password — **change it** |
| `ALMLIGHT_DATABASE_URL` | set by compose | SQLAlchemy URL (`postgresql+psycopg://…`) for external databases |
| `ALMLIGHT_SECRET_KEY` | generated, stored in `/data/secret_key` | Session signing key |
| `ALMLIGHT_ADMIN_USERNAME` / `ALMLIGHT_ADMIN_PASSWORD` | `admin` / generated | First administrator (empty installation only) |
| `ALMLIGHT_DEMO_DATA` | `false` | Load the demo project and demo users |
| `ALMLIGHT_DEMO_SIGN_IN` | `true` | `false` on a server others can reach: the demo users get passwords nobody knows (the default password `demo1234` would be public) |
| `ALMLIGHT_DEMO_OPEN_ROLE` | empty | `viewer`, `contributor` or `reviewer`: every signed-in user can open the demo project with this role |
| `ALMLIGHT_LOGIN_MAX_FAILURES` / `ALMLIGHT_LOGIN_WINDOW_SECONDS` | `10` / `900` | Failed sign-ins per user name within the window before further attempts are refused (three times as many per client address); `0` switches it off |
| `ALMLIGHT_COOKIE_SECURE` | `false` | `true` behind HTTPS |
| `ALMLIGHT_MAX_UPLOAD_MB` | `100` | Upload limit per file |
| `ALMLIGHT_MAX_IMAGE_MB` | `15` | Size limit of images in rich text |
| `ALMLIGHT_COLLAB_LEAVE_GRACE_SECONDS` | `8` | Live editing: save this long after the last editor left |
| `ALMLIGHT_COLLAB_IDLE_SECONDS` | `300` | Live editing: save after this idle time while people are connected |
| `ALMLIGHT_SESSION_HOURS` | `12` | Session lifetime |
| `ALMLIGHT_CORS_ORIGINS` | – | JSON list, only if another web origin calls the API |
| `ALMLIGHT_LOG_LEVEL` | `INFO` | Log level |
| `ALMLIGHT_PUBLIC_URL` | – | Public address, e.g. `https://alm.example.com` (links in e-mails, SSO redirect behind a proxy) |
| `ALMLIGHT_SMTP_HOST` / `_PORT` | – / `587` | Mail server for notification digests; e-mail is off while host or sender is empty |
| `ALMLIGHT_SMTP_USER` / `_PASSWORD` | – | SMTP login (optional) |
| `ALMLIGHT_SMTP_FROM` | – | Sender address, e.g. `Ariadne <alm@example.com>` |
| `ALMLIGHT_SMTP_SECURITY` | `starttls` | `starttls`, `ssl` (port 465) or `none` (internal relay) |
| `ALMLIGHT_EMAIL_DIGEST_SECONDS` | `60` | How often the background worker sends digests; notifications younger than 30 s wait for the next round |
| `ALMLIGHT_OIDC_ISSUER` | – | OpenID Connect issuer URL; SSO is off while issuer or client id is empty |
| `ALMLIGHT_OIDC_CLIENT_ID` / `_CLIENT_SECRET` | – | Client registered at the identity provider (confidential client, authorization code + PKCE) |
| `ALMLIGHT_OIDC_SCOPES` | `openid profile email` | Requested scopes (add the scope that delivers `groups` if the IdP needs one) |
| `ALMLIGHT_OIDC_LABEL` | `Single sign-on` | Button text on the sign-in page, e.g. `Sign in with Microsoft` |
| `ALMLIGHT_OIDC_USERNAME_CLAIM` | `preferred_username` | Claim used as user name (Entra ID: the UPN, e.g. `alex@example.com`; with `email` only the part before `@`) |
| `ALMLIGHT_OIDC_ADMIN_GROUP` | – | Members of this group (`groups` claim) become administrators |
| `ALMLIGHT_OIDC_ALLOW_SIGNUP` | `true` | Create users on first sign-in; `false`: only users that already exist may sign in |

### Single sign-on (OIDC)

1. Register an application at the identity provider (Microsoft Entra ID: *App registrations*; Keycloak: a
   confidential client) with the redirect URI `<ALMLIGHT_PUBLIC_URL>/api/v1/auth/oidc/callback`.
2. Set `ALMLIGHT_OIDC_ISSUER` (Entra ID: `https://login.microsoftonline.com/<tenant>/v2.0`; Keycloak:
   `https://<host>/realms/<realm>`), client id and secret, and `ALMLIGHT_PUBLIC_URL`; restart the app.
3. The sign-in page shows the SSO button next to the local login. New users are created on their first sign-in
   (project roles are still assigned by project managers); members of `ALMLIGHT_OIDC_ADMIN_GROUP` become
   administrators. Local accounts (e.g. the bootstrap admin) keep working as a fallback.

The ID token is verified (issuer, audience, expiry, signature against the provider's JWKS, nonce); the login uses
the authorization code flow with PKCE and a short-lived signed state cookie.

### Notification e-mails

With SMTP configured, users receive one digest e-mail with their unread notifications (watched items, own items,
approvals, @mentions) at most every `ALMLIGHT_EMAIL_DIGEST_SECONDS`; notifications read in the app before are not
mailed. Users switch digests off on their account page. Set `ALMLIGHT_PUBLIC_URL` so that the mails link to the items.

## 8.4 Backup and restore

Two things to back up: the database and the `/data` volume (files + secret key).

```bash
# backup
docker compose exec -T db pg_dump -U almlight -Fc almlight > almlight-$(date +%F).dump
docker run --rm -v almlight_app-data:/data -v "$PWD":/backup alpine tar czf /backup/almlight-files-$(date +%F).tgz -C /data .

# restore (on a stopped app)
docker compose stop app
docker compose exec -T db pg_restore -U almlight -d almlight --clean --if-exists < almlight-2026-10-22.dump
docker run --rm -v almlight_app-data:/data -v "$PWD":/backup alpine sh -c "cd /data && tar xzf /backup/almlight-files-2026-10-22.tgz"
docker compose start app
```

Per-project archives (JSON incl. history, links and baselines) can be downloaded by managers
(*Settings → Import / Export*) and imported into another installation by an administrator.

## 8.5 Upgrade

```bash
git pull
docker compose up -d --build     # migrations run automatically on start
```

Take a backup first. Database migrations are versioned with Alembic (`backend/migrations`).
Upgrading from 0.3 to 0.4 converts all item texts from Markdown to rich text once (content-preserving).

## 8.6 Monitoring

- `GET /api/v1/health` (also the container health check) — checks the database connection.
- Logs: `docker compose logs -f app`.
- Audit integrity: *Administration → Verify* or `GET /api/v1/admin/audit/verify`.

## 8.7 Development

```bash
# backend tests (real PostgreSQL in Docker)
docker compose -f compose.test.yaml run --rm backend-tests
# lint
docker compose -f compose.test.yaml run --rm --no-deps backend-tests ruff check .
# frontend type check and build (no local Node needed)
docker run --rm -v "$PWD/frontend":/web -w /web node:22-alpine sh -c "npm ci && npm run build"
# browser E2E tests against a fresh stack with demo data
docker compose -f compose.test.yaml up -d --build app
docker compose -f compose.test.yaml run --rm e2e
docker compose -f compose.test.yaml down
```

Frontend hot reload: run the backend (`docker compose up -d`), then
`docker run --rm -it -p 5173:5173 -e API_URL=http://host.docker.internal:48080 -v "$PWD/frontend":/web -w /web node:22-alpine npm run dev`.

Regenerate pinned Python dependencies after editing `backend/requirements.in`:

```bash
docker run --rm -v "$PWD/backend":/src -w /src python:3.12-slim sh -c \
  "pip install -q -r requirements.in && pip freeze > requirements.txt"
```

## 8.8 Reverse proxy and WebSockets

Live editing and live updates use two WebSocket endpoints (`/api/v1/collab/…`, `/api/v1/live`). The proxy must forward
the upgrade and the original host; the application refuses WebSocket connections whose `Origin` does not match the
host (or `ALMLIGHT_CORS_ORIGINS`).

```nginx
location / {
    proxy_pass http://app:8000;
    proxy_http_version 1.1;
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection $connection_upgrade;   # map $http_upgrade $connection_upgrade { default upgrade; "" close; }
    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_read_timeout 1h;
}
```

Traefik and Caddy forward WebSockets without extra configuration. Live sessions are held in the application process,
so run a single app container (the default).
