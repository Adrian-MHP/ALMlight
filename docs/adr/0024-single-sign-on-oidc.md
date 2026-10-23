# ADR-0024 Single sign-on with OpenID Connect

**Context.** SME customers run Microsoft Entra ID or Keycloak and expect single sign-on; ADR-0010 deferred OIDC.
Options: SAML (enterprise-wide but heavy XML signature handling), LDAP bind (passwords pass through the app), OIDC
(standard for modern identity providers, brokers SAML/LDAP when needed).

**Decision.** OIDC authorization code flow with PKCE, configured by environment variables. Discovery and JWKS are
fetched from the issuer; the ID token's signature, issuer, audience, expiry and nonce are verified; state, nonce and
PKCE verifier travel in a short-lived signed cookie. Users are created on first sign-in (configurable) or matched by
user name; a configured group in the `groups` claim maps to the administrator flag; project roles stay in Ariadne.
The session afterwards is the normal cookie session; local accounts remain as fallback.

**Consequences.** + Works with Entra ID, Keycloak, Okta, Auth0; LDAP/SAML through the IdP. + No passwords of SSO
users in Ariadne. − Group-to-project-role mapping is not automatic yet. − User names from the IdP may be e-mail-like;
mentions support that form.
