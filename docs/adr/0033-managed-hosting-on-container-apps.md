# ADR-0033 Shared installations run as a single managed container, not as a scaled-out service

**Context.** Ariadne had only been run with Docker Compose on a machine someone owns. The first installation several
colleagues share had to be reachable over the internet with company sign-on, cheap enough for a pilot (tens of euros
per month) and close to what a customer installation would look like. Azure Container Apps was chosen over a virtual
machine because it is managed; the alternative of making the application horizontally scalable first would have meant
moving live co-editing rooms, presence and the background workers out of the process (a message broker or an external
room service) before anyone could use the system.

**Decision.** A shared installation is **one container of the existing single image** with a managed database and a
mounted directory for attachments, not a scaled-out service: the replica count is pinned to exactly one
(`min = max = 1`, never zero), PostgreSQL is a managed Flexible Server reached with `sslmode=require`, and only
`/data/files` is mounted from durable storage (Azure Files). Everything else below `/data` — Git mirrors, the SysML
cache, temporary uploads — is treated as a rebuildable cache, and `ALMLIGHT_SECRET_KEY` is supplied as a secret so
that sessions and stored tokens survive a new revision. Sign-in uses the identity provider (OIDC) with local accounts
as a fallback. The platform terminates TLS and the application trusts `X-Forwarded-*` for scheme, host and the
WebSocket Content-Security-Policy. The deployment is described in [18](../18-azure-container-apps.md) and in the
README; it is not committed as infrastructure code until a second installation needs it.

**Consequences.** + A pilot installation costs about the price of a small virtual machine, is patched by the platform
and uses the same image and migrations as every other installation, so nothing in the product becomes
Azure-specific. + The one-process assumptions of co-editing, presence and the workers stay valid, which keeps the
code simple. − No horizontal scaling and a restart drops editing rooms and presence (unsaved drafts are recovered
from the database at the next start); a request is limited by the platform's ingress timeout, which can cut very
large imports; attachments sit on an SMB share rather than object storage. − The topology has to be set up by hand
(or scripted later) and the per-installation settings have to be kept outside the repository.
