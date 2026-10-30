# Changelog — Plateforme CAPI

## 30/10/2026

- **Documentation** : ajout du runbook opérationnel
  `docs/CAPI-PLATFORM-RUNBOOK.md` (prérequis, réseau, image, limites, dépannage).
- **Management cluster** : installation de **CAPI v1.14.3**, **CAPO v0.15.1**,
  **ORC v2.0.3** et du RBAC `capi-platform-role/binding`.
- **Cluster de test** : `vxlan-test-01` (1 CP + 1 worker, v1.31.6,
  `10.13.0.0/24`) créé via l'API, validé `Available`.
  - Calico : `100.64.0.0/16`, `ipipMode: Never`, `vxlanMode: Always`.
  - MTU pod : **1400** (underlay 1450).
- **Image** : `git.systalink.fr:5050/mouhmedsn02/capi_platform_v2/capi-platform-backend:vxlan-20261025b`
  déployée, `imagePullSecret: gitlab-registry`. Hotfix ConfigMap retiré.
- **OpenStack / Octavia** : diagnostic des LB en `ERROR/OFFLINE` (amphora).
  Quota de ports du projet tenant relevé de 500 à **1000** ; quotas du projet
  `service` (Octavia) relevés (2000 ports / 300 instances / 600 cores / 600 Go).
  Le provisioning d'amphora reste à corriger côté admin Octavia.
- **`main`** mis à jour et poussé (`f7c297c`).

## 29/10/2026

- **Correctif CNI / réseau** :
  - pod CIDR par défaut **`100.64.0.0/16`** ;
  - **`192.0.0.0/8` interdit** (pod et nœuds) ;
  - validation **côté serveur** du `node_cidr` : chevauchement réel
    (`ipaddress.overlaps`) + plages interdites + lock anti-course ;
  - Calico en **VXLAN** (`ipipMode: Never`, `vxlanMode: Always`), MTU auto ;
  - patch du manifest Calico dans `post_install.py` ;
  - RBAC mis à jour (secrets en écriture, groupe `ipam.cluster.x-k8s.io`) ;
  - documentation réseau dans le README.
- Commit `afda2fb` puis `f7c297c` (image `vxlan-20261025b`).

## 27/10/2026

- Analyse de l'incident `datacloud-platform` : le pod CIDR `192.168.0.0/16`
  englobait la DB on-prem `192.168.120.250` → trafic routé dans le tunnel IPIP.
  Décision : bannir `192.0.0.0/8` et passer en VXLAN pour les nouveaux clusters.
