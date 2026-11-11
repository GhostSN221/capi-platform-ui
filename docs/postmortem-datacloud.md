# Postmortem: `datacloud-platform` cluster network failure

**Status:** Resolved  
**Severity:** High — workload cluster unusable  
**Component:** CAPI/CAPO cluster networking (pod CIDR + Calico CNI)  
**Fix commit:** `35cbb07` — `fix(cni): VXLAN + pod CIDR 100.64/16, forbid 192/8, enforce node CIDR overlap`  
**Last updated:** 2026-11-11

> **Evidence note:** this postmortem is reconstructed from the repository README, code comments and commit history. The repository does not contain production telemetry, so exact wall-clock timestamps and the number of affected workloads are not claimed. The failure mode and the fix are verifiable in code and tests.

---

## Summary

A workload cluster named `datacloud-platform` was created with the old pod CIDR default `192.168.0.0/16`. That range overlapped the on-prem database at `192.168.120.250`. Pod traffic destined for the database was routed into the Calico tunnel instead of leaving through the gateway. At the same time, Calico was using IPIP/CrossSubnet, which OpenStack port security blocked, so pod-to-pod connectivity also failed.

The cluster could not serve its workloads. It was recreated after switching to a CGNAT pod CIDR (`100.64.0.0/16`) and Calico VXLAN, and the platform now rejects unsafe CIDRs before they reach OpenStack.

---

## Impact

- One workload cluster (`datacloud-platform`) was unusable for its intended workloads.
- Pod-to-pod traffic failed.
- Pods could not reliably reach the on-prem database at `192.168.120.250`.
- The affected cluster was recreated with the corrected network settings.
- No customer data loss is claimed here; the repository contains no production telemetry to support or deny that statement.

---

## Timeline

Timestamps are intentionally relative: the repository preserves the sequence of changes, not production incident timestamps.

| Phase | Event |
|---|---|
| 1. Creation | `datacloud-platform` was created with the default pod CIDR `192.168.0.0/16` and Calico IPIP/CrossSubnet. |
| 2. Symptoms | Workloads could not reach the on-prem database at `192.168.120.250`; pod-to-pod traffic failed. |
| 3. Diagnosis | The pod CIDR overlapped the on-prem `192.168.x` range. OpenStack port security blocked the direct pod-IP routing that IPIP/CrossSubnet relies on. |
| 4. Fix | Pod CIDR changed to `100.64.0.0/16`; Calico switched to VXLAN (`ipipMode: Never`, `vxlanMode: Always`, MTU auto). |
| 5. Recovery | The affected cluster was recreated; clusters created before the fix with `192.168.0.0/16` must also be recreated. |
| 6. Prevention | Server-side CIDR validation, a create lock, UI feedback, documentation and regression tests were added. |

---

## Root cause

Two contributing causes had to be fixed together:

### 1. Overlapping pod CIDR

`192.168.0.0/16` covered the on-prem database address `192.168.120.250`. From the pod's point of view, the database was inside the cluster network, so traffic was sent through the Calico tunnel instead of the default gateway. The database was reachable from the node but not from the pods.

### 2. IPIP/CrossSubnet blocked by OpenStack

Calico was using IPIP/CrossSubnet. On OpenStack, port security (anti-spoofing) prevents the direct routing of pod IPs that this mode expects. Pod-to-pod traffic therefore failed even after the CIDR overlap was understood.

The fix had to change both the address plan and the encapsulation mode.

---

## Resolution

The platform now enforces the following:

- **Pod CIDR:** `100.64.0.0/16` (CGNAT), configured by `POD_CIDR`.
- **Service CIDR:** `10.96.0.0/12`, configured by `SERVICE_CIDR`.
- **CNI:** Calico VXLAN with `ipipMode: Never`, `vxlanMode: Always` and automatic MTU (`CALICO_MTU=0`).
- **Node CIDR range:** `10.6.0.0/24` → `10.250.0.0/24`.
- **Forbidden ranges:** `192.0.0.0/8`, `172.16.0.0/12`, `169.254.0.0/16`, `127.0.0.0/8`, `0.0.0.0/8`, `224.0.0.0/4`, `240.0.0.0/4`, `255.255.255.255/32`, plus `100.64.0.0/10` for the node network.
- **Overlap check:** the requested node CIDR is compared with every existing OpenStack subnet using `ipaddress.overlaps`.
- **Server-side enforcement:** `POST /api/clusters` returns HTTP 400 for an invalid or overlapping CIDR. The browser validation is only a convenience.
- **Race protection:** a lock serialises CIDR check + cluster creation so two concurrent requests cannot claim the same `/24` before the Neutron subnet exists.

Implementation references:

- `backend/app/services/network.py` — forbidden ranges, parsing, overlap check, `suggest_cidr`.
- `backend/app/routers/clusters.py` — `_validate_cluster_networks`, `_CLUSTER_CREATE_LOCK`, create endpoint.
- `backend/app/config.py` — VXLAN/CIDR defaults.
- `backend/app/templates/cluster_template.yaml.j2` — rendered CAPI/CAPO manifests.

---

## Detection and response gaps

- There was no preflight validation against existing OpenStack subnets before cluster creation.
- The unsafe default was accepted by the API; validation existed only as a UI convenience.
- There was no automated alert on pod-to-database failures or pod-to-pod packet loss.
- There was no regression test for forbidden CIDRs.

The first two gaps are closed in code. The alerting gap remains an operational action item.

---

## Action items

| Action | Status | Evidence |
|---|---|---|
| Reject `192.0.0.0/8` and other forbidden pod CIDRs server-side | Done | `_validate_cluster_networks`, `FORBIDDEN_NETWORKS` |
| Validate node CIDR against existing OpenStack subnets | Done | `network.check_cidr` |
| Switch Calico to VXLAN and disable IPIP | Done | `config.py`, `k8s/deployment-backend.yaml` |
| Serialise CIDR check + create | Done | `_CLUSTER_CREATE_LOCK` |
| Add regression tests for every forbidden range | Done | `backend/tests/test_network.py` |
| Show CIDR validation feedback in the UI | Done | `cluster_create.html` + `/api/network/check-cidr` |
| Recreate clusters created with the old `192.168.0.0/16` default | Done / operational | README incident note |
| Alert on provisioning failures and pod-to-database errors | Open | Needs Prometheus/alerting |
| Add provisioning duration and failure-rate metrics | Open | Roadmap |
| Add a kind-based end-to-end test | Open | Roadmap |

---

## What went well

- The failure was reproducible, which made the root cause identifiable.
- The fix was implemented at the API layer, so curl requests cannot bypass it.
- The incident produced a permanent regression suite, not just a one-off patch.
- The defaults are now documented in code, the README and the Kubernetes deployment.

## What went poorly

- The original default CIDR was unsafe for this environment.
- Validation was treated as a UI concern instead of a server invariant.
- There was no alerting on the failure mode.
- Existing clusters had to be recreated because the pod CIDR is immutable.

## Where we got lucky

- The repository retained enough context (README, code comments, commit history) to reconstruct the failure.
- The corrected design could be tested without OpenStack by exercising the validation layer directly.

---

## Verification

The guardrail is covered by a parametrized regression suite. Run:

```bash
cd capi-platform/backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
pytest tests/test_network.py -q
```

Expected behaviour:

```text
192.168.0.0/16  -> rejected (overlaps 192.0.0.0/8)
10.6.0.0/24     -> rejected (overlaps an existing OpenStack subnet)
100.64.0.0/16   -> rejected for the node network (CGNAT is reserved for pods)
10.8.0.0/24     -> accepted in the demo network
```

The API-level regression is also exercised by `tests/test_api.py::test_create_cluster_rejects_forbidden_node_cidr`, which expects HTTP 400.

---

## References

- Fix commit: `35cbb07` — `fix(cni): VXLAN + pod CIDR 100.64/16, forbid 192/8, enforce node CIDR overlap`
- `README.md` — network policy and production quick start
- `backend/app/services/network.py`
- `backend/app/routers/clusters.py`
- `backend/tests/test_network.py`
- `backend/tests/test_api.py`
