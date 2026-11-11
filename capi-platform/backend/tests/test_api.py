import uuid


async def test_healthz(client):
    response = await client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


async def test_login_and_me(client):
    login = await client.post("/api/auth/login", json={"username": "demo", "password": "demo"})
    assert login.status_code == 200
    token = login.json()["access_token"]

    me = await client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 200
    assert me.json()["username"] == "demo"
    assert me.json()["is_admin"] is True


async def test_login_rejects_bad_password(client):
    response = await client.post("/api/auth/login", json={"username": "demo", "password": "nope"})
    assert response.status_code == 401


async def test_me_rejects_invalid_token(client):
    response = await client.get("/api/auth/me", headers={"Authorization": "Bearer not-a-token"})
    assert response.status_code == 401


async def test_non_admin_cannot_read_admin_routes(client):
    username = f"viewer-{uuid.uuid4().hex[:6]}"
    register = await client.post(
        "/api/auth/register",
        json={"username": username, "password": "viewer-password"},
    )
    assert register.status_code == 200, register.text

    login = await client.post(
        "/api/auth/login",
        json={"username": username, "password": "viewer-password"},
    )
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
    response = await client.get("/api/admin/users", headers=headers)
    assert response.status_code == 403


async def test_root_redirects_to_dashboard(client):
    response = await client.get("/", follow_redirects=False)
    assert response.status_code in (302, 307)
    assert response.headers["location"] == "/dashboard"


async def test_demo_clusters_are_seeded(client, auth_headers):
    response = await client.get("/api/clusters/", headers=auth_headers)
    assert response.status_code == 200
    clusters = response.json()
    assert {c["name"] for c in clusters} == {"demo-prod", "demo-staging", "demo-dev"}
    assert {c["name"]: c["status"] for c in clusters}["demo-prod"] == "Ready"


async def test_cluster_machines(client, auth_headers):
    response = await client.get("/api/clusters/demo-prod/machines", headers=auth_headers)
    assert response.status_code == 200
    machines = response.json()
    assert len(machines) == 6
    assert all(m["ready"] for m in machines)


async def test_cluster_events(client, auth_headers):
    response = await client.get("/api/clusters/demo-prod/events", headers=auth_headers)
    assert response.status_code == 200
    assert {e["reason"] for e in response.json()} >= {"Provisioned", "PostInstallComplete"}


async def test_workload_events(client, auth_headers):
    response = await client.get("/api/clusters/demo-prod/workload-events", headers=auth_headers)
    assert response.status_code == 200
    events = response.json()
    assert len(events) >= 3
    assert any(e["namespace"] == "kube-system" for e in events)


async def test_workload_namespaces(client, auth_headers):
    response = await client.get("/api/clusters/demo-prod/namespaces", headers=auth_headers)
    assert response.status_code == 200
    assert "kube-system" in response.json()


async def test_workload_resources_pods(client, auth_headers):
    response = await client.get(
        "/api/clusters/demo-prod/resources?ns=default&kind=pods",
        headers=auth_headers,
    )
    assert response.status_code == 200
    pods = response.json()
    assert len(pods) == 3
    assert pods[0]["name"].startswith("demo-api")


async def test_workload_resources_other_kinds(client, auth_headers):
    for kind, expected in [("deployments", 2), ("services", 2), ("pvcs", 1)]:
        response = await client.get(
            f"/api/clusters/demo-prod/resources?ns=default&kind={kind}",
            headers=auth_headers,
        )
        assert response.status_code == 200, kind
        assert len(response.json()) == expected, kind


async def test_demo_kubeconfig_is_not_a_real_credential(client, auth_headers):
    response = await client.get("/api/clusters/demo-prod/kubeconfig", headers=auth_headers)
    assert response.status_code == 200
    assert "DEMO_MODE" in response.text


async def test_pod_logs(client, auth_headers):
    response = await client.get(
        "/api/clusters/demo-prod/pod-logs?ns=default&pod=demo-api&container=api&lines=10",
        headers=auth_headers,
    )
    assert response.status_code == 200
    assert "demo mode" in response.text


async def test_readiness_reports_ready_for_prod(client, auth_headers):
    response = await client.get("/api/clusters/demo-prod/readiness", headers=auth_headers)
    assert response.status_code == 200
    assert response.json()["ready"] is True


async def test_readiness_reports_not_ready_for_dev(client, auth_headers):
    response = await client.get("/api/clusters/demo-dev/readiness", headers=auth_headers)
    assert response.status_code == 200
    assert response.json()["ready"] is False


async def test_storage_test_succeeds_for_prod(client, auth_headers):
    response = await client.post("/api/clusters/demo-prod/test-storage", headers=auth_headers)
    assert response.status_code == 200
    assert response.json()["status"] == "Bound"


async def test_storage_test_rejects_unready_cluster(client, auth_headers):
    response = await client.post("/api/clusters/demo-dev/test-storage", headers=auth_headers)
    assert response.status_code == 409


async def test_network_check_rejects_incident_cidr(client, auth_headers):
    response = await client.get(
        "/api/network/check-cidr?cidr=192.168.0.0/16",
        headers=auth_headers,
    )
    assert response.status_code == 200
    body = response.json()
    assert body["available"] is False
    assert "192.0.0.0/8" in body["conflicts"]


async def test_network_suggest_returns_free_cidr(client, auth_headers):
    response = await client.get("/api/network/suggest-cidr", headers=auth_headers)
    assert response.status_code == 200
    assert response.json()["cidr"] == "10.8.0.0/24"


async def test_create_cluster_rejects_forbidden_node_cidr(client, auth_headers):
    name = f"pytest-{uuid.uuid4().hex[:6]}"
    response = await client.post("/api/clusters/", headers=auth_headers, json={
        "name": name,
        "k8s_version": "v1.31.6",
        "cp_flavor": "k8s.master.small",
        "worker_flavor": "k8s.node.small",
        "master_count": 1,
        "worker_count": 1,
        "node_cidr": "192.168.0.0/16",
    })
    assert response.status_code == 400
    assert "192.0.0.0/8" in response.json()["detail"]


async def test_create_and_delete_cluster(client, auth_headers):
    name = f"pytest-{uuid.uuid4().hex[:6]}"
    create = await client.post("/api/clusters/", headers=auth_headers, json={
        "name": name,
        "k8s_version": "v1.31.6",
        "cp_flavor": "k8s.master.small",
        "worker_flavor": "k8s.node.small",
        "master_count": 1,
        "worker_count": 1,
        "node_cidr": "10.8.0.0/24",
    })
    assert create.status_code == 200, create.text
    assert create.json()["name"] == name

    clusters = (await client.get("/api/clusters/", headers=auth_headers)).json()
    assert name in {c["name"] for c in clusters}

    delete = await client.delete(f"/api/clusters/{name}", headers=auth_headers)
    assert delete.status_code == 200

    clusters = (await client.get("/api/clusters/", headers=auth_headers)).json()
    assert name not in {c["name"] for c in clusters}


async def test_cluster_templates_are_seeded(client, auth_headers):
    response = await client.get("/api/cluster-templates/", headers=auth_headers)
    assert response.status_code == 200
    names = {t["name"] for t in response.json()}
    assert {"Dev - Small", "Prod - Standard", "Database Cluster"} <= names


async def test_admin_users_and_audit(client, auth_headers):
    users = await client.get("/api/admin/users", headers=auth_headers)
    assert users.status_code == 200
    assert any(u["username"] == "demo" for u in users.json())

    audit = await client.get("/api/admin/audit", headers=auth_headers)
    assert audit.status_code == 200
    assert len(audit.json()) >= 3


async def test_tenants_are_visible_to_admin(client, auth_headers):
    response = await client.get("/api/tenants/", headers=auth_headers)
    assert response.status_code == 200
    assert any(t["name"] == "demo" for t in response.json())


async def test_versions_and_flavors(client, auth_headers):
    versions = await client.get("/api/templates/k8s-versions", headers=auth_headers)
    flavors = await client.get("/api/templates/flavors", headers=auth_headers)
    assert versions.status_code == 200
    assert "v1.31.6" in versions.json()
    assert flavors.status_code == 200
    assert any(f["name"] == "k8s.node.medium" for f in flavors.json())
