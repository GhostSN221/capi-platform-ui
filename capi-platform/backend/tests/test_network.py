import ipaddress

import pytest
from fastapi import HTTPException

from app.routers.clusters import _validate_cluster_networks
from app.services import network

# Captured before demo mode rebinds the name; used to test the real parser.
ORIGINAL_GET_USED_NETWORKS = network.get_used_networks


def test_incident_cidr_192_168_is_rejected():
    """Regression for datacloud-platform: 192.0.0.0/8 must never be accepted."""
    result = network.check_cidr("192.168.0.0/16")
    assert result["available"] is False
    assert "192.0.0.0/8" in result["conflicts"]


@pytest.mark.parametrize("cidr", [
    "192.0.0.0/8",
    "172.16.0.0/12",
    "169.254.0.0/16",
    "127.0.0.0/8",
    "0.0.0.0/8",
    "224.0.0.0/4",
    "240.0.0.0/4",
    "255.255.255.255/32",
    "100.64.0.0/16",
])
def test_forbidden_node_cidrs(cidr):
    assert network.check_cidr(cidr)["available"] is False


def test_overlap_with_existing_openstack_subnet_is_rejected():
    result = network.check_cidr("10.6.0.0/24")
    assert result["available"] is False
    assert "10.6.0.0/24" in result["conflicts"]


def test_free_subnet_is_accepted():
    result = network.check_cidr("10.8.0.0/24")
    assert result["available"] is True
    assert result["conflicts"] == []


def test_invalid_cidr_is_rejected():
    result = network.check_cidr("not-a-cidr")
    assert result["available"] is False
    assert "CIDR invalide" in result["reason"]


def test_suggest_cidr_skips_used_and_forbidden_ranges():
    assert network.suggest_cidr() == "10.8.0.0/24"


def test_pod_cidr_192_is_rejected_server_side():
    with pytest.raises(HTTPException) as exc:
        _validate_cluster_networks("192.168.0.0/16", "10.96.0.0/12")
    assert exc.value.status_code == 400
    assert "192.0.0.0/8" in exc.value.detail


def test_pod_cidr_cgnat_is_accepted():
    _validate_cluster_networks("100.64.0.0/16", "10.96.0.0/12")


def test_pod_and_service_overlap_is_rejected():
    with pytest.raises(HTTPException) as exc:
        _validate_cluster_networks("10.96.0.0/16", "10.96.0.0/12")
    assert exc.value.status_code == 400
    assert "service_cidr" in exc.value.detail


def test_parse_rejects_ipv6():
    with pytest.raises(ValueError, match="IPv4"):
        network._parse("2001:db8::/32")


def test_get_used_cidrs_serializes_networks(monkeypatch):
    monkeypatch.setattr(
        network,
        "get_used_networks",
        lambda: [ipaddress.ip_network("10.6.0.0/24"), ipaddress.ip_network("10.7.0.0/24")],
    )
    assert network.get_used_cidrs() == ["10.6.0.0/24", "10.7.0.0/24"]


def test_get_used_networks_parses_and_skips_invalid_subnets(monkeypatch):
    class FakeSubnet:
        def __init__(self, cidr):
            self.cidr = cidr

    class FakeNetworkAPI:
        def subnets(self):
            return [FakeSubnet("10.9.0.0/24"), FakeSubnet("not-a-cidr"), FakeSubnet("10.10.0.0/24")]

    class FakeConnection:
        network = FakeNetworkAPI()

    monkeypatch.setattr(network, "_os_connect", lambda: FakeConnection())
    monkeypatch.setattr(network, "get_used_networks", ORIGINAL_GET_USED_NETWORKS)
    assert [str(n) for n in network.get_used_networks()] == ["10.9.0.0/24", "10.10.0.0/24"]


def test_os_connect_requires_clouds_yaml(monkeypatch):
    monkeypatch.delenv("OS_CLOUDS_YAML", raising=False)
    with pytest.raises(RuntimeError, match="OS_CLOUDS_YAML"):
        network._os_connect()


def test_suggest_cidr_raises_when_range_is_exhausted(monkeypatch):
    used = [ipaddress.ip_network(f"10.{octet}.0.0/24") for octet in range(6, 250)]
    monkeypatch.setattr(network, "get_used_networks", lambda: used)
    with pytest.raises(RuntimeError, match="Aucun CIDR"):
        network.suggest_cidr()
