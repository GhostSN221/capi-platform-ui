import pytest
from pydantic import ValidationError

from app.schemas.cluster import ClusterCreate
from app.schemas.cluster_template import ClusterTemplateCreate


def payload(**overrides):
    data = {
        "name": "demo-prod",
        "k8s_version": "v1.31.6",
        "cp_flavor": "k8s.master.medium",
        "worker_flavor": "k8s.node.medium",
        "master_count": 3,
        "worker_count": 3,
        "node_cidr": "10.8.0.0/24",
        "tenant_id": 1,
    }
    data.update(overrides)
    return data


def test_valid_cluster_payload():
    cluster = ClusterCreate(**payload())
    assert cluster.name == "demo-prod"
    assert cluster.master_count == 3


def test_cluster_worker_count_default():
    data = payload(master_count=1)
    data.pop("worker_count")
    cluster = ClusterCreate(**data)
    assert cluster.worker_count == 3
    assert cluster.node_cidr == "10.8.0.0/24"


@pytest.mark.parametrize("name", ["Prod", "prod_cluster", "-prod", "prod-", "", "  "])
def test_invalid_cluster_names(name):
    with pytest.raises(ValidationError):
        ClusterCreate(**payload(name=name))


def test_master_count_must_be_1_3_or_5():
    with pytest.raises(ValidationError):
        ClusterCreate(**payload(master_count=2))


def test_node_cidr_must_be_valid():
    with pytest.raises(ValidationError):
        ClusterCreate(**payload(node_cidr="10.8.0.0/33"))


def test_schema_accepts_192_but_server_rejects_it():
    # The schema validates format; the incident guardrail is enforced by
    # network.check_cidr() in the create endpoint.
    cluster = ClusterCreate(**payload(node_cidr="192.168.0.0/16"))
    assert cluster.node_cidr == "192.168.0.0/16"


def test_template_defaults():
    template = ClusterTemplateCreate(
        name="Demo",
        k8s_version="v1.31.6",
        cp_flavor="k8s.master.small",
        worker_flavor="k8s.node.small",
    )
    assert template.master_count == 1
    assert template.worker_count == 3
