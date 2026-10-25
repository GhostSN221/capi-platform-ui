# CAPI Platform UI

I got tired of writing YAML every time I needed to spin up a Kubernetes cluster with CAPI on OpenStack.

One cluster = 7+ manifests. Three clients = do the math. And if you get one `apiVersion` wrong, you spend the next hour debugging a cryptic 422 error.

So I built this.

---

## What it does

A web UI that takes a form input and provisions a full Kubernetes cluster via CAPI/CAPO on OpenStack — no YAML required.

It also handles everything that comes *after* provisioning, which is usually the painful part:

- **Automatic post-install** — Calico CNI, OpenStack CCM and Cinder CSI are deployed automatically once the cluster is up. No manual steps.
- **Live log viewer** — read events and logs directly from the workload cluster without switching contexts
- **Resource explorer** — browse Pods, Deployments, Services and PVCs on any cluster from the UI
- **Scale & upgrade** — change worker count or K8s version without touching kubectl
- **Cinder storage test** — verify your CSI setup with one click
- **Multi-tenancy** — each client gets their own namespace and OpenStack credentials

---

## Who is this for

Anyone who manages CAPI clusters on OpenStack and is tired of copy-pasting YAML.

---

## Stack

- Backend: FastAPI + Jinja2 + PostgreSQL
- Runs in-cluster on the CAPI management cluster (no external kubeconfig needed)
- Targets CAPO v0.10+ / cluster.x-k8s.io v1beta2

---

## Quick start

```bash
git clone https://github.com/GhostSN221/capi-platform-ui.git
cd capi-platform-ui/capi-platform
docker compose up -d

# Create first admin
curl -X POST http://localhost:8000/api/auth/register \
  -H "Content-Type: application/json" \
  -d '{"username":"admin","password":"yourpassword"}'

# Promote to admin
docker compose exec postgres psql -U capi capidb \
  -c "UPDATE users SET is_admin=true WHERE username='admin';"

# Open http://localhost:8000
```

> Mount your kubeconfig for local testing:
> ```yaml
> volumes:
>   - ~/.kube/config:/root/.kube/config:ro
> ```

---

## Kubernetes deployment

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

Edit `k8s/secret.yaml` before applying — change `SECRET_KEY` to something strong.

---

## OpenStack credentials per tenant

```bash
kubectl create namespace my-tenant
kubectl create secret generic my-cloud-cloud-config \
  --from-file=clouds.yaml=./clouds.yaml \
  -n my-tenant
```

Then create the tenant from the Admin page in the UI.

---

## Roadmap

- Vault integration for OpenStack secrets
- OIDC authentication
- Helm chart
- Connect to an existing Kubernetes manager (Rancher, etc.)

---

## Réseau des clusters créés (important)

Depuis l'incident `datacloud-platform`, la plateforme applique une politique réseau stricte :

- **Aucun `192.x.x.x`** n'est autorisé, ni pour le pod CIDR ni pour le réseau des nœuds
  (`192.0.0.0/8` est refusé).
- **Pod CIDR** par défaut : `100.64.0.0/16` (`POD_CIDR`), non modifiable depuis l'UI.
- **Réseau des nœuds** : `10.6.0.0/24` → `10.250.0.0/24`, validé **côté serveur** :
  - chevauchement réel (`ipaddress.overlaps`) avec tous les sous-réseaux OpenStack existants ;
  - plages interdites : `192.0.0.0/8`, `172.16.0.0/12`, `169.254.0.0/16`, `127.0.0.0/8`,
    `100.64.0.0/10` (pour le réseau nœuds), multicast/réservé.
- **CNI** : Calico en **VXLAN** (`ipipMode: Never`), MTU auto
  (`vxlan.calico` = MTU underlay − 50, ex. 1400 sur un underlay 1450).
- La validation est faite dans `POST /api/clusters` (pas seulement dans l'UI) :
  un CIDR interdit ou qui chevauche renvoie **HTTP 400**.
- Les clusters créés avant ce correctif avec `192.168.0.0/16` doivent être recréés.

### Variables d'environnement

| Variable | Défaut | Rôle |
|---|---|---|
| `POD_CIDR` | `100.64.0.0/16` | CIDR des pods (Calico) |
| `SERVICE_CIDR` | `10.96.0.0/12` | CIDR des services |
| `CALICO_IPIP_MODE` | `Never` | IPIP interdit (anti-spoofing OpenStack) |
| `CALICO_VXLAN_MODE` | `Always` | Encapsulation VXLAN |
| `CALICO_MTU` | `0` | 0 = auto (underlay − 50) |

### Prérequis du cluster de management

CAPI, CAPO et ORC doivent être installés sur le cluster de management :

```bash
kubectl apply --server-side -f \
  https://github.com/k-orc/openstack-resource-controller/releases/download/v2.0.3/install.yaml
clusterctl init --infrastructure openstack
kubectl apply -f k8s/rbac.yaml
```

---

## Contributing

Issues and PRs are welcome.

---

## License

Apache 2.0
