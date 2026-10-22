# ADR-0010 Local accounts, cookie sessions, API tokens; OIDC later

**Context.** Many SMEs use Microsoft 365, but an on-premise installation must also work standalone.

**Decision.** Local users with Argon2 password hashes; browser sessions as signed JWT in an httpOnly SameSite=Lax
cookie; personal access tokens (hashed, revocable, expiring) for integrations. Project roles
viewer/contributor/reviewer/manager; system administrators. The first administrator is bootstrapped from
configuration. OIDC (Entra ID, Keycloak) will plug into the same `current_user` dependency.

**Consequences.** + Works offline and on day one. − Until OIDC, user lifecycle is manual.
