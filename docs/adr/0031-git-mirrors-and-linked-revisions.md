# ADR-0031 Git: server-side mirrors, an indexed commit history and linked revisions

**Context.** Polarion-style traceability from requirements to code needs the commits of the customer's repositories
next to the items — also for repositories the server cannot receive webhooks from (on-premises installations behind
firewalls, local demos). Provider APIs differ (GitHub, GitLab, Bitbucket, Azure DevOps) and have rate limits.

**Decision.** Repositories are connected per project by their HTTPS clone URL and mirrored with the `git` command
line into bare repositories on the server (branches and tags only); a background worker fetches them periodically,
a push webhook triggers an immediate fetch. New commits are indexed in the database (metadata, changed files, line
counts); commits whose message mentions an item key are linked to the item (*linked revision*), further revisions can
be linked by hand. Browsing (commit diffs, file tree, file contents, history) reads the mirror directly; provider APIs
are only used for extras (GitHub pull requests). Tokens are sealed with a key derived from the installation secret
and passed to Git through the environment; only HTTPS (and an allowed local directory) is accepted, Git runs without
prompts or credential helpers and with timeouts.

**Consequences.** + Works with any Git server, offline and without rate limits; the same index serves item pages,
queries and the repository browser. + No code is executed from repositories (bare mirrors, no hooks). − Disk space
for mirrors and a first fetch time for large repositories; very large histories are indexed up to a limit.
