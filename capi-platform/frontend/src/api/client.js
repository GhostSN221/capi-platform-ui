const BASE = import.meta.env.VITE_API_URL || "/api";

async function request(method, path, body) {
  const token = localStorage.getItem("token");
  const res = await fetch(`${BASE}${path}`, {
    method,
    headers: { "Content-Type": "application/json", ...(token ? { Authorization: `Bearer ${token}` } : {}) },
    ...(body ? { body: JSON.stringify(body) } : {}),
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export const api = {
  login:         (u, p) => request("POST",   "/auth/login",        { username: u, password: p }),
  me:            ()     => request("GET",    "/auth/me"),
  register:      (u, p) => request("POST",   "/auth/register",     { username: u, password: p }),
  listClusters:  ()     => request("GET",    "/clusters/"),
  createCluster: (b)    => request("POST",   "/clusters/",          b),
  deleteCluster: (n)    => request("DELETE", `/clusters/${n}`),
  getMachines:   (n)    => request("GET",    `/clusters/${n}/machines`),
  getKubeconfig: async (n) => {
    const token = localStorage.getItem("token");
    const res = await fetch(`${BASE}/clusters/${n}/kubeconfig`, { headers: { Authorization: `Bearer ${token}` } });
    return res.text();
  },
  listTenants:   ()     => request("GET",  "/tenants/"),
  createTenant:  (b)    => request("POST", "/tenants/", b),
  getVersions:   ()     => request("GET",  "/templates/k8s-versions"),
  getFlavors:    ()     => request("GET",  "/templates/flavors"),
};
