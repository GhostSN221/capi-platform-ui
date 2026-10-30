# AGENTS.md

## Repository layout

- The runnable project lives in `capi-platform/`; the repo root only contains `README.md` and `docs/`.
- `capi-platform/backend/` is the whole application: FastAPI API + Jinja UI (`app/templates/`, `app/static/`).
- `capi-platform/frontend/` is an unused React/Vite prototype — nothing in compose, k8s, or the backend references it. Edit the Jinja templates and `app/static/app.js`/`style.css` instead.
- `capi-platform/k8s/` holds deployment manifests. `docs/CAPI-PLATFORM-RUNBOOK.md` is the operational source of truth.

## Commands

```bash
cd capi-platform
docker compose up -d --build    # UI/API at http://localhost:8001
docker compose logs -f backend
```

- Compose maps host `8001` to container `8000`; the README's `localhost:8000` is stale.
- Run the backend outside Docker with `cd capi-platform/backend && uvicorn app.main:app --reload`. Start from `backend/` — `services/capi.py` loads `app/templates` relative to the CWD.
- There is no test suite, linter, formatter, or CI. Do not assume `pytest`/`ruff` exists; verify by starting the app and hitting `/healthz` or the relevant endpoint.
- Compose expects `capi-platform/backend/config/clouds.yaml` (gitignored; create it) and bind-mounts `~/.kube/config`.

## Runtime prerequisites

- Requires a reachable CAPI management cluster (in-cluster service account, otherwise local kubeconfig) and live OpenStack access.
- `OS_CLOUDS_YAML` must point to a `clouds.yaml` file; only the first cloud entry is used. `OS_EXTERNAL_NETWORK_ID` is required by setup/tenant creation.
- `/api/network/*` and cluster creation query real OpenStack. K8s versions and flavors are hardcoded in `app/routers/templates.py`, not queried.
- Post-install downloads manifests at runtime from `raw.githubusercontent.com` (Calico, cloud-provider-openstack, ingress-nginx), so the backend environment needs outbound internet.
- `post_install.py` and the storage tests shell out to `kubectl` at `KUBECTL_PATH` (default `/usr/local/bin/kubectl`). The Dockerfile does not install kubectl; compose mounts the host binary. Custom images must provide it.
- Redis is configured (`REDIS_URL`) but unused; the README's `k8s/deployment-redis.yaml` does not exist.

## Database / schema

- No migrations. Startup `init_db()` runs `Base.metadata.create_all` plus ad-hoc `ALTER TABLE ... ADD COLUMN IF NOT EXISTS`; `seed_db()` seeds/updates the five default cluster templates.
- Alembic is in `requirements.txt` but has no config or migration directory. Do not make `alembic upgrade` part of the workflow; if you add a column, extend the startup ALTER list so existing databases get it.

## Cluster creation flow

- `POST /api/clusters` (`app/routers/clusters.py`) validates CIDRs, loads `clouds.yaml` from the server file, creates/uses the tenant cloud secret, then `capi.create_cluster()` renders `app/templates/cluster_template.yaml.j2` into 7 CAPI/CAPO manifests and applies them with the dynamic Kubernetes client.
- Node CIDR validation is server-side in `app/services/network.py`: forbidden ranges + real overlap against all OpenStack subnets + a create lock. Keep UI and API validation consistent.
- API versions are mixed: CAPI `cluster.x-k8s.io/v1beta2`, CAPO `infrastructure.cluster.x-k8s.io/v1beta1`. Do not assume everything is v1beta2.
- The template hardcodes environment-specific values: `externalNetwork.id`, a security-group ID, `sshKeyName: capi-key`, DNS `8.8.8.8`, and image filter `ubuntu-2404-kube-<k8s_version>`. Note that `OS_EXTERNAL_NETWORK_ID` does not drive `OpenStackCluster.spec.externalNetwork`.
- Post-install (Calico, CCM, Cinder CSI, ingress-nginx) runs in a daemon thread inside the API process. It is not durable: a pod restart loses in-flight provisioning; the deployment runs 2 replicas. Search logs for `[post-install]`.
- Deletion uses `app/services/force_delete.py` as a background watcher that releases FIPs and strips finalizers. Do not replace it with a plain delete.

## Network constraints (do not regress)

- `192.0.0.0/8` is forbidden for both pod and node CIDRs, along with `172.16.0.0/12`, `169.254.0.0/16`, `127.0.0.0/8`, and multicast/reserved ranges.
- Pods use `100.64.0.0/16`, services `10.96.0.0/12`; Calico uses VXLAN (`ipipMode: Never`, `vxlanMode: Always`) with auto MTU.
- Enforcement is in `create_cluster` and `network.py`, not just the HTML form. Invalid/overlapping CIDRs must return HTTP 400.

## Deployment

- Build/push from `capi-platform/backend` using the registry path in the runbook.
- Apply order: namespace → rbac → configmap/secret → postgres → backend → services. Skip the README's `deployment-redis.yaml` step.
- `k8s/deployment-backend.yaml` runs 2 replicas, requires the `gitlab-registry` pull secret, and carries the image tag. `k8s/secret.yaml` contains a placeholder `SECRET_KEY`.
- The app needs `k8s/rbac.yaml` (cluster-wide CAPI/CAPO, namespace, secret write, event/node/pod read) before it can provision anything.

## Conventions / gotchas

- User-facing strings, comments, and docs are French; keep that style when editing UI or documentation.
- `POST /api/auth/register` is open, but the first user is not an admin. Promote manually with `UPDATE users SET is_admin=true WHERE username='...';` or admin endpoints return 403.
- Never commit `clouds.yaml`, kubeconfigs, `.env`, or certificates; `.gitignore` already covers them.
