# CAPI Platform UI

> A lightweight web interface for deploying and managing Kubernetes clusters using [Cluster API (CAPI)](https://cluster-api.sigs.k8s.io/) and [Cluster API Provider OpenStack (CAPO)](https://github.com/kubernetes-sigs/cluster-api-provider-openstack).

![License](https://img.shields.io/badge/license-Apache%202.0-blue)
![Python](https://img.shields.io/badge/python-3.12-blue)
![FastAPI](https://img.shields.io/badge/FastAPI-0.111-green)
![Kubernetes](https://img.shields.io/badge/kubernetes-1.28%2B-blue)

---

## Why this project?

Provisioning Kubernetes clusters with CAPI/CAPO requires writing 7+ YAML manifests by hand, knowing the exact API versions for your specific CAPI/CAPO release, managing OpenStack credentials per namespace, and debugging cryptic 422 validation errors.

**CAPI Platform UI** turns this into a simple form:

```
Name → K8s version → Flavors → Worker count → Create
```

The platform handles manifest generation, namespace isolation, and automatic post-install (Calico CNI, OpenStack CCM, Cinder CSI) transparently.

---

## Features

- **Cluster lifecycle** — create, scale, upgrade and delete clusters from a web UI
- **Automatic post-install** — Calico CNI, OpenStack Cloud Controller Manager and Cinder CSI are installed automatically after cluster provisioning
- **Multi-tenancy** — each tenant gets its own Kubernetes namespace and OpenStack credentials
- **Storage testing** — built-in Cinder CSI test (creates a PVC, binds it, then cleans up)
- **Resource explorer** — browse Pods, Deployments, Services and PVCs on workload clusters directly from the UI
- **Cluster events & logs** — real-time event viewer with configurable time window
- **Cluster templates** — save reusable configurations and apply them from the creation wizard
- **Audit log** — tracks all platform actions with user, timestamp and details
- **Kubeconfig download** — one-click kubeconfig export per cluster
- **In-cluster deployment** — runs inside the CAPI management cluster using a ServiceAccount (no external kubeconfig needed)

---

## Architecture

```
Browser
   │
   ▼
FastAPI backend (Jinja2 UI + REST API)
   │
   ├── PostgreSQL  (users, tenants, clusters, audit)
   ├── Redis       (session cache)
   └── Kubernetes API (in-cluster)
          │
          ├── CAPI CRDs  (Cluster, MachineDeployment, ...)
          └── CAPO CRDs  (OpenStackCluster, OpenStackMachineTemplate, ...)
```

---

## Prerequisites

- Kubernetes management cluster with CAPI and CAPO installed
- OpenStack cloud with:
  - Nova, Neutron, Cinder available
  - Ubuntu images named `ubuntu-2404-kube-<version>` in Glance
- `kubectl` configured to point to the management cluster
- Docker (for local development)

---

## Quick start (local development)

```bash
# 1. Clone the repo
git clone https://github.com/GhostSN221/capi-platform-ui.git
cd capi-platform-ui/capi-platform

# 2. Start services
docker compose up -d

# 3. Create the first admin user
curl -X POST http://localhost:8000/api/auth/register \
  -H "Content-Type: application/json" \
  -d '{"username":"admin","password":"your-password"}'

# 4. Promote to admin (connect to postgres)
docker compose exec postgres psql -U capi capidb \
  -c "UPDATE users SET is_admin=true WHERE username='admin';"

# 5. Open http://localhost:8000
```

> **Note:** For local development, mount your kubeconfig into the backend container:
> ```yaml
> volumes:
>   - ~/.kube/config:/root/.kube/config:ro
> ```

---

## Kubernetes deployment

### 1. Apply manifests

```bash
kubectl apply -f k8s/namespace.yaml
kubectl apply -f k8s/rbac.yaml
kubectl apply -f k8s/configmap.yaml
kubectl apply -f k8s/secret.yaml
kubectl apply -f k8s/deployment-postgres.yaml
kubectl apply -f k8s/deployment-redis.yaml
kubectl apply -f k8s/deployment-backend.yaml
kubectl apply -f k8s/services.yaml
```

### 2. Edit the secret before applying

```bash
# k8s/secret.yaml
stringData:
  SECRET_KEY: "replace-with-a-strong-random-key"
```

### 3. Create your first tenant

Each tenant maps to a Kubernetes namespace and a set of OpenStack credentials.

```bash
# Create the namespace
kubectl create namespace my-tenant-ns

# Create the OpenStack cloud config secret
kubectl create secret generic my-cloud-cloud-config \
  --from-file=clouds.yaml=./clouds.yaml \
  -n my-tenant-ns
```

Then create the tenant from the Admin page in the UI, using:
- **Namespace**: `my-tenant-ns`
- **os_cloud**: the cloud name defined in your `clouds.yaml`

---

## Configuration

| Variable | Default | Description |
|---|---|---|
| `DATABASE_URL` | `postgresql+asyncpg://capi:capi@postgres/capidb` | PostgreSQL connection string |
| `REDIS_URL` | `redis://redis:6379` | Redis connection string |
| `SECRET_KEY` | `change-me-in-production` | JWT signing key — **must be changed** |

---

## CAPO compatibility

This project targets **CAPO v0.10+** with the following API versions:

| Resource | API Version |
|---|---|
| Cluster, MachineDeployment | `cluster.x-k8s.io/v1beta2` |
| KubeadmControlPlane | `controlplane.cluster.x-k8s.io/v1beta2` |
| KubeadmConfigTemplate | `bootstrap.cluster.x-k8s.io/v1beta2` |
| OpenStackCluster, OpenStackMachineTemplate | `infrastructure.cluster.x-k8s.io/v1beta1` |

---

## Stack

| Layer | Technology |
|---|---|
| Backend | Python 3.12, FastAPI, SQLAlchemy (async), Jinja2 |
| Database | PostgreSQL 16 |
| Cache | Redis 7 |
| Auth | JWT (python-jose + passlib) |
| K8s client | kubernetes-python |
| Container | Docker, Kubernetes |

---

## Roadmap

- [ ] Vault integration for OpenStack secrets
- [ ] OIDC / Keycloak authentication
- [ ] Cluster health dashboard with metrics
- [ ] Multi-management-cluster support
- [ ] Helm chart for easy installation

---

## Contributing

Contributions are welcome! Please open an issue first to discuss what you would like to change.

```bash
# Fork the repo, then:
git checkout -b feat/my-feature
git commit -m "feat: my feature"
git push origin feat/my-feature
# Open a Pull Request
```

---

## License

Apache License 2.0 — see [LICENSE](LICENSE) for details.

---

## Acknowledgements

Built on top of the amazing work by the [Cluster API](https://github.com/kubernetes-sigs/cluster-api) and [CAPO](https://github.com/kubernetes-sigs/cluster-api-provider-openstack) communities.K
