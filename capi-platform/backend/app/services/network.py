import ipaddress
import os
import yaml
import openstack


# ---------------------------------------------------------------------------
# Plages interdites pour les réseaux de clusters.
#
# 192.0.0.0/8 couvre tous les 192.x.x.x, dont les réseaux "entreprise"
# (192.168.0.0/16) qui ont causé l'incident datacloud-platform : le pod CIDR
# 192.168.0.0/16 englobait la DB on-prem 192.168.120.250 et le trafic partait
# dans le tunnel au lieu de sortir vers la passerelle.
#
# On interdit donc TOUT 192.x, ainsi que les autres plages privées/réservées.
# ---------------------------------------------------------------------------
FORBIDDEN_NETWORKS = [
    ipaddress.ip_network("192.0.0.0/8"),       # tout 192.x.x.x
    ipaddress.ip_network("172.16.0.0/12"),     # privé RFC1918
    ipaddress.ip_network("169.254.0.0/16"),    # link-local
    ipaddress.ip_network("127.0.0.0/8"),       # loopback
    ipaddress.ip_network("0.0.0.0/8"),         # "this network"
    ipaddress.ip_network("224.0.0.0/4"),       # multicast
    ipaddress.ip_network("240.0.0.0/4"),       # réservé
    ipaddress.ip_network("255.255.255.255/32"),
]

# Le réseau des nœuds ne doit pas non plus chevaucher le pod CIDR (CGNAT).
NODE_FORBIDDEN_NETWORKS = FORBIDDEN_NETWORKS + [
    ipaddress.ip_network("100.64.0.0/10"),
]


def _os_connect():
    path = os.getenv("OS_CLOUDS_YAML", "")
    if not path or not os.path.exists(path):
        raise RuntimeError("OS_CLOUDS_YAML non configuré sur le serveur")
    with open(path) as f:
        content = f.read()
    os_cloud = list(yaml.safe_load(content).get("clouds", {}).keys())[0]
    os.environ["OS_CLIENT_CONFIG_FILE"] = path
    return openstack.connect(cloud=os_cloud)


def get_used_networks() -> list[ipaddress.IPv4Network]:
    """Tous les sous-réseaux OpenStack existants (tous réseaux du projet)."""
    conn = _os_connect()
    out: list[ipaddress.IPv4Network] = []
    for subnet in conn.network.subnets():
        try:
            out.append(ipaddress.ip_network(subnet.cidr, strict=False))
        except (ValueError, TypeError):
            continue
    return out


def get_used_cidrs() -> list[str]:
    return [str(n) for n in get_used_networks()]


def _parse(cidr: str) -> ipaddress.IPv4Network:
    net = ipaddress.ip_network(cidr, strict=False)
    if net.version != 4:
        raise ValueError("seuls les CIDR IPv4 sont acceptés")
    return net


def _forbidden_conflicts(net: ipaddress.IPv4Network, forbidden) -> list[str]:
    return [str(f) for f in forbidden if net.overlaps(f)]


def check_cidr(cidr: str) -> dict:
    """Vérifie un CIDR de réseau de nœuds : format, plages interdites, overlap.

    Retourne {cidr, available, reason, conflicts}.
    """
    try:
        net = _parse(cidr)
    except ValueError as exc:
        return {"cidr": cidr, "available": False, "reason": f"CIDR invalide: {exc}", "conflicts": []}

    forbidden = _forbidden_conflicts(net, NODE_FORBIDDEN_NETWORKS)
    if forbidden:
        return {
            "cidr": cidr,
            "available": False,
            "reason": f"plage interdite (chevauche {', '.join(forbidden)})",
            "conflicts": forbidden,
        }

    conflicts = [str(u) for u in get_used_networks() if net.overlaps(u)]
    if conflicts:
        return {
            "cidr": cidr,
            "available": False,
            "reason": f"chevauche un sous-réseau existant ({', '.join(conflicts[:5])})",
            "conflicts": conflicts,
        }

    return {"cidr": cidr, "available": True, "reason": "disponible", "conflicts": []}


def suggest_cidr() -> str:
    """Premier /24 libre dans 10.6–250, sans overlap ni plage interdite."""
    used = get_used_networks()
    for octet in range(6, 250):
        candidate = ipaddress.ip_network(f"10.{octet}.0.0/24")
        if _forbidden_conflicts(candidate, NODE_FORBIDDEN_NETWORKS):
            continue
        if any(candidate.overlaps(u) for u in used):
            continue
        return str(candidate)
    raise RuntimeError("Aucun CIDR /24 disponible dans la plage 10.6–250.0.0/24")
