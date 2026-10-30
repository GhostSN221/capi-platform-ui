# Runbook — Plateforme CAPI (capi-platform)

Dernière mise à jour : **30/10/2026**

Ce document reprend l'architecture, les prérequis, la politique réseau, le
déploiement et les limites connues de la plateforme `capi-platform`.

---

## 1. Vue d'ensemble

`capi-platform` est l'interface (UI + API FastAPI + PostgreSQL/Redis) qui crée
des clusters Kubernetes via **Cluster API (CAPI)** et **CAPO** (provider
OpenStack).

```
Management cluster (ex. all-platforms-sow)
├── ns capi-platform  : UI + backend + Postgres/Redis
├── ns capi-system    : CAPI core (cluster-api, kubeadm bootstrap/control-plane)
├── ns capo-system    : CAPO (OpenStack : Nova/Neutron/Cinder/Octavia)
├── ns orc-system     : ORC (dépendance CAPO >= v0.12)
└── ns cert-manager   : certificats webhooks

Workload cluster (créé par CAPI/CAPO)
├── VMs OpenStack (control plane + workers)
├── Calico (VXLAN)
├── CCM OpenStack + Cinder CSI
└── ingress-nginx
```

Flux de création :

1. `POST /api/clusters` (nom, version K8s, flavors, `master_count`, `worker_count`, `node_cidr`).
2. Validation réseau + création du secret `clouds.yaml` du tenant.
3. Rendu de `cluster_template.yaml.j2` → 7 manifests (Cluster, OpenStackCluster,
   KubeadmControlPlane, MachineDeployment, templates).
4. CAPO crée réseau/sous-réseau/routeur, security groups, VMs, FIP/LB.
5. kubeadm initialise le control plane, les workers rejoignent.
6. Post-install : Calico, cloud.conf, CCM, CSI Cinder, StorageClass,
   ingress-nginx, tolerations/providerID.

---

## 2. Prérequis du cluster de management

| Composant | Version validée |
|---|---|
| Cluster API | **v1.14.3** |
| CAPO | **v0.15.1** |
| ORC | **v2.0.3** |
| cert-manager | v1.21.2 |
| Kubernetes | v1.31 / v1.34 |

Installation :

```bash
# ORC (dépendance obligatoire de CAPO >= v0.12)
kubectl apply --server-side -f \
  https://github.com/k-orc/openstack-resource-controller/releases/download/v2.0.3/install.yaml

# CAPI + CAPO
clusterctl init --infrastructure openstack

# RBAC de l'application
kubectl apply -f capi-platform/k8s/rbac.yaml
```

Le RBAC doit autoriser :

- les groupes `cluster.x-k8s.io`, `infrastructure.cluster.x-k8s.io`,
  `bootstrap.cluster.x-k8s.io`, `controlplane.cluster.x-k8s.io`,
  `ipam.cluster.x-k8s.io` ;
- les `namespaces` (get/list/watch/create) ;
- les `secrets` **en écriture** (get/list/watch/create/update/patch/delete) ;
- `events`, `nodes`, `pods` en lecture.

Chaque tenant doit avoir un namespace et un secret `<os_cloud>-cloud-config`
(clouds.yaml) référencé par `identityRef`.

---

## 3. Politique réseau (IMPORTANT)

Depuis l'incident `datacloud-platform` (pod CIDR `192.168.0.0/16` qui englobait
la DB on-prem `192.168.120.250`), la plateforme applique une politique stricte :

| Élément | Valeur / règle |
|---|---|
| `POD_CIDR` | **`100.64.0.0/16`** |
| `SERVICE_CIDR` | `10.96.0.0/12` |
| Plages interdites | **`192.0.0.0/8`** (tout `192.x.x.x`), `172.16.0.0/12`, `169.254.0.0/16`, `127.0.0.0/8`, `0.0.0.0/8`, multicast/réservé |
| CIDR nœuds | `10.6.0.0/24` → `10.250.0.0/24`, **`100.64.0.0/10` interdit** |
| Validation | `ipaddress.overlaps()` contre **tous** les subnets OpenStack existants + lock anti-course |
| CNI | Calico **VXLAN** (`ipipMode: Never`, `vxlanMode: Always`) |
| MTU | `CALICO_MTU=0` (auto) → **1400** sur underlay 1450 |

Variables d'environnement :

| Variable | Défaut | Rôle |
|---|---|---|
| `POD_CIDR` | `100.64.0.0/16` | CIDR des pods |
| `SERVICE_CIDR` | `10.96.0.0/12` | CIDR des services |
| `CALICO_IPIP_MODE` | `Never` | IPIP interdit (anti-spoofing OpenStack) |
| `CALICO_VXLAN_MODE` | `Always` | Encapsulation VXLAN |
| `CALICO_MTU` | `0` | 0 = auto (underlay − 50) |

Validation côté serveur :

- `GET /api/network/check-cidr?cidr=...` → `available` + `reason` ;
- `POST /api/clusters` avec un CIDR interdit/chevauchement → **HTTP 400** ;
- `suggest_cidr()` ne propose que des `/24` libres et hors plages interdites.

> Les clusters créés avant ce correctif avec `192.168.0.0/16` doivent être
> recréés. Le correctif n'est pas rétroactif.

---

## 4. Création d'un cluster

Depuis l'UI ou l'API :

```json
{
  "name": "mon-cluster",
  "k8s_version": "v1.31.6",
  "cp_flavor": "k8s.master.small",
  "worker_flavor": "k8s.node.small",
  "master_count": 1,
  "worker_count": 3,
  "node_cidr": "10.13.0.0/24"
}
```

Points de contrôle :

```bash
# ressources CAPI
kubectl -n <tenant> get clusters,openstackclusters,machines,kubeadmcontrolplanes

# statut
kubectl -n <tenant> get cluster <nom> -o jsonpath='{.status.phase}'

# Calico dans le workload
KUBECONFIG=<kubeconfig-workload> kubectl get ippools -o custom-columns=\
'NAME:.metadata.name,CIDR:.spec.cidr,IPIP:.spec.ipipMode,VXLAN:.spec.vxlanMode'
# attendu : 100.64.0.0/16, Never, Always

# MTU pod
kubectl -n default run mtu --image=nicolaka/netshoot --restart=Never -- sleep infinity
kubectl -n default exec mtu -- ip -o link show eth0
# attendu : mtu 1400
```

Cluster de test validé (30/10/2026) : `vxlan-test-01`, 1 CP + 1 worker,
v1.31.6, réseau nœuds `10.13.0.0/24`, statut **Available**, Calico VXLAN,
MTU pod **1400**.

---

## 5. Image et déploiement

Image de référence :

```
git.systalink.fr:5050/mouhmedsn02/capi_platform_v2/capi-platform-backend:vxlan-20261025b
```

Build / push :

```bash
cd capi-platform/backend
docker build -t git.systalink.fr:5050/mouhmedsn02/capi_platform_v2/capi-platform-backend:<tag> .
docker push git.systalink.fr:5050/mouhmedsn02/capi_platform_v2/capi-platform-backend:<tag>
```

Déploiement :

```bash
kubectl -n capi-platform set image deploy/capi-platform-backend \
  backend=git.systalink.fr:5050/mouhmedsn02/capi_platform_v2/capi-platform-backend:<tag>

kubectl -n capi-platform patch deploy capi-platform-backend --type strategic -p \
  '{"spec":{"template":{"spec":{"imagePullSecrets":[{"name":"gitlab-registry"}]}}}}'
```

Le secret `gitlab-registry` doit exister dans le namespace `capi-platform`.
Les variables réseau (`POD_CIDR`, `SERVICE_CIDR`, `CALICO_*`) peuvent être
définies dans le deployment.

---

## 6. Performances / limites OpenStack

Mesures sur `vxlan-test-01` (flavors 2 vCPU) :

| Test | Résultat |
|---|---|
| Pod→pod même nœud | ~12 Gbit/s |
| Pod→pod inter-nœuds (VXLAN) | **~135 Mbit/s** |
| Nœud→nœud TCP | ~700 Mbit/s |
| UDP 512 o | ~52 Mbit/s (~12k pps) |
| UDP 1400 o | ~132 Mbit/s (~12k pps) |

Interprétation : plafond d'environ **12 000 paquets/s** sur le réseau tenant
OpenStack (OVS/VXLAN) ; le VXLAN (UDP 4789) est donc limité à ~135 Mbit/s.
Le TCP nœud→nœud est limité par les petits flavors (~700 Mbit/s). Ce n'est pas
un problème CAPI/Calico : c'est l'infrastructure OpenStack. Pour des charges
réseau, utiliser des flavors plus gros et faire vérifier le policer pps.

---

## 7. Problèmes connus / limites

1. **Octavia / LoadBalancer** : sur certains clusters, la création des LB
   Octavia part en `ERROR/OFFLINE` (amphora), donc l'ingress reste en
   `EXTERNAL-IP <pending>`. Le quota de ports du projet tenant était dépassé
   (500 / 508) → augmenté à 1000, et les quotas du projet `service` (Octavia)
   augmentés. Le reste nécessite les logs du worker Octavia / un admin.
2. **NAT hairpin / cert-manager HTTP-01** : sans NAT loopback sur le FortiGate,
   le self-check HTTP-01 depuis l'intérieur du cluster échoue. Utiliser
   **DNS-01** ou un override CoreDNS vers l'ingress.
3. **Readiness** : `/api/clusters/<nom>/readiness` ne vérifie pas l'IP externe
   de l'ingress (le cluster peut être `Ready` avec ingress `<pending>`).
4. **Anciens clusters** : ceux créés en `192.168.0.0/16` ou en IPIP doivent
   être recréés.

---

## 8. Dépannage

```bash
# CAPI / CAPO
kubectl -n <tenant> get clusters,openstackclusters,machines
kubectl -n <tenant> get events --sort-by=.lastTimestamp
kubectl -n capo-system logs deploy/capo-controller-manager --tail=100

# kubeconfig du workload
kubectl -n <tenant> get secret <cluster>-kubeconfig \
  -o jsonpath='{.data.value}' | base64 -d > /tmp/<cluster>.kubeconfig

# Octavia
openstack loadbalancer list
openstack loadbalancer amphora list
openstack quota show <project>
```

---

## 9. Références

- [Changelog](CHANGELOG.md)
- Code : `capi-platform/backend/app`
- Template : `capi-platform/backend/app/templates/cluster_template.yaml.j2`
- RBAC : `capi-platform/k8s/rbac.yaml`
