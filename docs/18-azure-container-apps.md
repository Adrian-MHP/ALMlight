# 18 Running Ariadne on Azure Container Apps (0.8.2)

How to run Ariadne in an Azure resource group so that colleagues can reach it with their company account. It was
written from the first deployment (a team of MHP colleagues in one Entra tenant); steps marked † describe the
intended result but had not been run end to end when this was written. All names below are placeholders — nothing
in this repository identifies a subscription, tenant or resource group, and secrets never belong here.

## 18.1 What you get

```
Browser ──https──▶ Container Apps ingress ──▶ ariadne (1 container, 0.5 vCPU / 1 GiB)
                                                 ├─▶ PostgreSQL Flexible Server (B1ms, database "almlight")
                                                 ├─▶ Azure Files share mounted at /data/files   (attachments)
                                                 └─▶ Entra ID (single sign-on, OpenID Connect)
Azure Container Registry holds the image (built from the public repository).
```

Why it looks like this — what the application assumes:

| Assumption | Consequence |
|---|---|
| Live co-editing, presence and the background workers (webhooks, e-mail digests, Git fetch) run inside the one application process | Exactly **one replica**: `--min-replicas 1 --max-replicas 1`. Never scale to zero (editing sessions and workers would stop). |
| Only `/data/files` (attachments) must survive a restart | Mount the Azure Files share there. Git mirrors, the SysML cache and temporary files below `/data` are rebuilt automatically. |
| The session key also encrypts stored Git and SysML tokens | Set `ALMLIGHT_SECRET_KEY` explicitly (a Container Apps secret). Without it a key is generated into the data directory and lost on restart. |
| Imports and Git fetches can run for minutes | The Container Apps ingress ends a request after about four minutes (check the current Azure limits); imports of very large models may fail there. |
| No Azure Blob backend | Attachments live on the file share (SMB). |

Cost (rough, check the Azure price calculator): PostgreSQL B1ms about 15 €, the container about 10–15 €, registry,
storage and logs about 8 € per month.

## 18.2 Before you start

- **Rights**: *Contributor* on the resource group is enough. You cannot register resource providers (that needs a
  subscription role) — check instead that they are registered:
  `az provider show -n Microsoft.App --query registrationState -o tsv` for `Microsoft.App`,
  `Microsoft.OperationalInsights`, `Microsoft.ContainerRegistry`, `Microsoft.DBforPostgreSQL`, `Microsoft.Storage`.
  `AuthorizationFailed` on `az provider register` is harmless when they already say `Registered`.
- **Entra**: your account needs the right to register applications (otherwise the IT team creates the registration
  from step 6 and hands you the application ID and a client secret).
- **Policies**: look at *Policies* and *Tags* of the resource group. `RequestDisallowedByPolicy` names the rule that
  blocked a step (allowed regions, required tags, public network access).
- **Azure Cloud Shell (Bash)** works and needs no installation. The session is **ephemeral**: variables and files are
  gone after about 20 minutes without input. Keep the tab open during long steps, and set the variables again after
  a restart (the names are found with `az acr list -g $RG -o table` and `az postgres flexible-server list -g $RG -o table`).
  Bash expands `!` in double quotes (`event not found`): use single quotes for texts with an exclamation mark.
- Never paste secrets into chats or tickets. Commands that print credentials are marked below; generate secrets in
  the shell, and read them back from the container app when needed (`az containerapp secret show`).

## 18.3 Deployment

```bash
RG=<resource-group>; LOC=germanywestcentral          # a region with Postgres Burstable and Container Apps
S=$(openssl rand -hex 3); echo "suffix: $S"          # note it: it makes the global names unique
ACR=ariadneacr$S; PG=ariadne-pg-$S; SA=ariadnefiles$S
az extension add --name containerapp --upgrade
```

**1. Registry and image** — the build runs in Azure and pulls the public repository, so no Docker is needed locally
(an ARM Mac cannot build the required `linux/amd64` image without emulation):

```bash
az acr create -g $RG -n $ACR -l $LOC --sku Basic --admin-enabled true
az acr build -r $ACR -t ariadne:0.8.2 https://github.com/Adrian-MHP/ALMlight.git#main
az acr repository show-tags -n $ACR --repository ariadne -o tsv
```

**2. Database** — the command prints the password in its result; copy it to a password manager, do not share the
terminal output (change it with `az postgres flexible-server update -g $RG -n $PG -p <new>` if it was exposed):

```bash
PGPW="$(openssl rand -hex 12)Aa1"                     # three character classes are required
az postgres flexible-server create -g $RG -n $PG -l $LOC --version 16 --tier Burstable --sku-name Standard_B1ms \
  --storage-size 32 --admin-user almlight --admin-password "$PGPW" --public-access 0.0.0.0 --yes -o none
az postgres flexible-server db create -g $RG -s $PG -n almlight -o none        # the database name option is -n
```

`--public-access 0.0.0.0` lets Azure services connect (the password still protects it). Tighten it later to the
outbound addresses of the container app (`properties.outboundIpAddresses`) or move to a private endpoint.

**3. File share for attachments:**

```bash
az storage account create -g $RG -n $SA -l $LOC --sku Standard_LRS --allow-blob-public-access false --min-tls-version TLS1_2 -o none
az storage share-rm create -g $RG --storage-account $SA --name ariadne-files --quota 20 -o none
```

**4. Environment and address:**

```bash
az containerapp env create -g $RG -n ariadne-env -l $LOC -o none
DOMAIN=$(az containerapp env show -g $RG -n ariadne-env --query properties.defaultDomain -o tsv)
FQDN=ariadne.$DOMAIN; echo "https://$FQDN"
```

**5. Sign-in with Entra ID** (single tenant; the client secret is shown once and expires after a year):

```bash
TENANT=$(az account show --query tenantId -o tsv)
APPID=$(az ad app create --display-name "Ariadne ALM" --sign-in-audience AzureADMyOrg \
  --web-redirect-uris "https://$FQDN/api/v1/auth/oidc/callback" --query appId -o tsv)
OIDCSECRET=$(az ad app credential reset --id $APPID --years 1 --query password -o tsv)
az ad sp create --id $APPID -o none
```

In the portal (*Enterprise applications → Ariadne ALM*): **Properties → Assignment required = Yes**, then
**Users and groups** → add the colleagues or a group. Only they can sign in.

**6. The application:**

```bash
SECKEY=$(openssl rand -base64 48)
read -rs -p 'Admin password (at least 8 characters): ' ADMINPW; echo
for v in RG ACR PG PGPW FQDN TENANT APPID OIDCSECRET SECKEY ADMINPW; do [ -n "${!v}" ] && echo "$v ok" || echo "$v MISSING"; done
az containerapp create -g $RG -n ariadne --environment ariadne-env \
  --image $ACR.azurecr.io/ariadne:0.8.2 --registry-server $ACR.azurecr.io \
  --registry-username "$(az acr credential show -n $ACR --query username -o tsv)" \
  --registry-password "$(az acr credential show -n $ACR --query 'passwords[0].value' -o tsv)" \
  --target-port 8000 --ingress external --min-replicas 1 --max-replicas 1 --cpu 0.5 --memory 1.0Gi \
  --secrets dburl="postgresql+psycopg://almlight:$PGPW@$PG.postgres.database.azure.com:5432/almlight?sslmode=require" \
            seckey="$SECKEY" adminpw="$ADMINPW" oidc="$OIDCSECRET" \
  --env-vars ALMLIGHT_DATABASE_URL=secretref:dburl ALMLIGHT_SECRET_KEY=secretref:seckey \
    ALMLIGHT_ADMIN_PASSWORD=secretref:adminpw ALMLIGHT_DEMO_DATA=false ALMLIGHT_COOKIE_SECURE=true \
    ALMLIGHT_PUBLIC_URL=https://$FQDN \
    ALMLIGHT_OIDC_ISSUER=https://login.microsoftonline.com/$TENANT/v2.0 ALMLIGHT_OIDC_CLIENT_ID=$APPID \
    ALMLIGHT_OIDC_CLIENT_SECRET=secretref:oidc "ALMLIGHT_OIDC_LABEL=Sign in with your company account" \
  --query properties.configuration.ingress.fqdn -o tsv
curl -s https://$FQDN/api/v1/health            # {"status":"ok","version":"0.8.2"}
```

The first start applies the database migrations (a minute). The password of the database must not contain
characters that need URL encoding (the generated one does not). Look at the start with
`az containerapp logs show -g $RG -n ariadne --tail 40` (`Running upgrade …`, `Ariadne … started`;
`Database not reachable` means password or firewall).

**7. † Keep attachments:**

```bash
SAKEY=$(az storage account keys list -g $RG -n $SA --query '[0].value' -o tsv)
az containerapp env storage set -g $RG -n ariadne-env --storage-name ariadnefiles \
  --azure-file-account-name $SA --azure-file-account-key "$SAKEY" --azure-file-share-name ariadne-files \
  --access-mode ReadWrite -o none
az containerapp show -g $RG -n ariadne -o json > app.json
jq '.properties.template.volumes = [{"name":"files","storageType":"AzureFile","storageName":"ariadnefiles","mountOptions":"uid=10001,gid=10001,file_mode=0770,dir_mode=0770"}]
    | .properties.template.containers[0].volumeMounts = [{"volumeName":"files","mountPath":"/data/files"}]' app.json > app2.json
az containerapp update -g $RG -n ariadne --yaml app2.json -o none
rm -f app.json app2.json        # they contain secrets
```

The container runs as user 10001, hence the mount options; drop them if Azure refuses them (the mount is usually
writable without). Upload an attachment, restart the revision and check that it is still there.

**8. First sign-in.** Open the address and sign in as `admin` with the password from step 6. Create the project
(template *systems engineering*). A colleague who signs in with the company account is created automatically with
the user name `<name>@<domain>` (lower case) and sees nothing until a project manager adds them under
*Project → Settings → Members*. To make a single-sign-on user an administrator, use the *Administration* page as
`admin`, or set `ALMLIGHT_OIDC_ADMIN_GROUP` to the object ID of an Entra group (the token must carry the
`groups` claim).

**9. Example project for everyone.** The application starts empty. To load the example project (*Smart Sensor
Platform*: requirements, architecture, variants, tests, risks, plans, a firmware repository) and let every colleague
who signs in open it, set three variables; the new revision loads it on start (about half a minute):

```bash
az containerapp update -g $RG -n ariadne --set-env-vars \
  ALMLIGHT_DEMO_DATA=true ALMLIGHT_DEMO_SIGN_IN=false ALMLIGHT_DEMO_OPEN_ROLE=contributor
```

- `ALMLIGHT_DEMO_SIGN_IN=false` is essential on an address others can reach: the demo users (`alex`, `rita`, `max`)
  then exist as colleagues in the data but get random passwords. Without it the published password `demo1234`
  would let anyone sign in as the demo manager.
- `ALMLIGHT_DEMO_OPEN_ROLE=contributor`: every signed-in colleague can open the project, read everything and try
  creating and editing items; approvals and configuration need a reviewer or manager. Use `viewer` for read-only.
  A project manager changes it later under *Project → Settings → Members → Everyone who signs in*. To give a
  colleague more (e.g. manager), add them as a member there; the higher role counts.
- The project is loaded once (when no project `DEMO` exists). Changes colleagues make stay; starting over is a
  database operation. The demo firmware repository below `/data` is written again after a restart (same commits).
- Single-sign-on users cannot give **electronic signatures** yet: a signature checks the user's own password, and
  single-sign-on users have none. They can read and edit; approvals that require a signature need a local account
  (see the open points in [14](14-beta-test-report.md)).

## 18.4 Operating

- **Update**: build a new tag and switch the app to it; the migrations run at start, and a failed start leaves the
  previous revision serving. † Roll back with `az containerapp revision list` / `activate`.

  ```bash
  az acr build -r $ACR -t ariadne:<version> https://github.com/Adrian-MHP/ALMlight.git#main
  az containerapp update -g $RG -n ariadne --image $ACR.azurecr.io/ariadne:<version>
  ```

- **Secrets**: `az containerapp secret show -g $RG -n ariadne --secret-name seckey --query value -o tsv`. Replace a
  secret with `az containerapp secret set … --secrets name=value` and restart the revision. The Entra client secret
  expires after the chosen period (create a new one with `az ad app credential reset`, then update `oidc`).
- **Backup**: PostgreSQL Flexible Server keeps point-in-time backups (seven days by default). Add share snapshots for
  the Azure Files share. Test a restore before relying on it; project archives (*Settings → Import / Export*) are an
  additional, tool-independent copy of items, versions, links and baselines.
- **Logs**: `az containerapp logs show -g $RG -n ariadne --follow`; the environment also writes to a Log Analytics
  workspace.
- **Costs**: stop the database (`az postgres flexible-server stop`) when the system is not used for days (Azure starts
  it again after seven days). Set a budget alert on the resource group.
- **Limits**: one replica, an ingress request limit of about four minutes, files on an SMB share. For more users or
  customers, plan a private network, more database capacity and a restore drill — see the architecture notes in
  [05](05-architecture.md).

## 18.5 Security notes

- Sign-in is protected: after 10 failed attempts per user name within 15 minutes (30 per client address) further
  attempts are refused with "try again in n minutes"; failures of existing users and the blocks are in the audit
  trail (`ALMLIGHT_LOGIN_MAX_FAILURES`, `ALMLIGHT_LOGIN_WINDOW_SECONDS`; 0 switches it off). Behind the ingress the
  client address comes from `X-Forwarded-For` and is not fully reliable, so the per-user-name limit is the real guard.
- The address is public. Entra *Assignment required* decides who can use single sign-on. The local `admin` account
  stays available: give it a long password, or restrict the ingress to the company's addresses:
  `az containerapp ingress access-restriction set -g $RG -n ariadne --rule-name company --ip-address <CIDR> --action Allow` †.
- Everything sensitive is a Container Apps secret (not visible in the revision's settings); nothing is stored in the
  image or the repository. Tokens for Git and SysML servers are entered in the application and stored encrypted with
  the session key.
- The database firewall allows Azure services (see step 2); tighten it before storing sensitive project data.

## 18.6 Problems seen in the first deployment

| Message | Cause and remedy |
|---|---|
| `AuthorizationFailed … register/action` | Providers can only be registered with a subscription role. Check the state with `az provider show`; if it says `Registered` carry on. |
| `bash: !: event not found` | An exclamation mark inside double quotes. Use single quotes. |
| `--name/-n required` for `db create` | The database name option is `-n`. |
| Azure CLI printed the database password | `flexible-server create` echoes it. Change it at once (`update -p`) and hide the output (`-o none`). |
| `NameNotAvailable` | Global names are taken: pick a new suffix. |
| Health check fails right after `create` | The first start runs migrations; wait a minute and read the logs. |
