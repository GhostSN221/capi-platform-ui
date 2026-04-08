const API = '/api';

function token() { return localStorage.getItem('token'); }

function requireAuth() {
    if (!token()) { window.location.href = '/login'; return false; }
    return true;
}

async function request(method, path, body, responseType) {
    const headers = { 'Content-Type': 'application/json' };
    if (token()) headers['Authorization'] = 'Bearer ' + token();
    const res = await fetch(API + path, {
        method,
        headers,
        ...(body ? { body: JSON.stringify(body) } : {})
    });
    if (res.status === 401) { logout(); return; }
    if (!res.ok) throw new Error(await res.text());
    return responseType === 'text' ? res.text() : res.json();
}

const api = {
    login:           (u, p) => request('POST',   '/auth/login',         { username: u, password: p }),
    me:              ()     => request('GET',    '/auth/me'),
    listClusters:    ()     => request('GET',    '/clusters/'),
    createCluster:   (b)    => request('POST',   '/clusters/',           b),
    deleteCluster:   (n)    => request('DELETE', `/clusters/${n}`),
    getMachines:     (n)    => request('GET',    `/clusters/${n}/machines`),
    getEvents:          (n)    => request('GET',    `/clusters/${n}/events`),
    getWorkloadEvents:  (n, since=60, limit=200) => request('GET', `/clusters/${n}/workload-events?since=${since}&limit=${limit}`),
    getNamespaces:      (n)                      => request('GET', `/clusters/${n}/namespaces`),
    getResources:       (n, ns, kind)            => request('GET', `/clusters/${n}/resources?ns=${ns}&kind=${kind}`),
    getPodLogs:         (n, ns, pod, ctr, lines) => request('GET', `/clusters/${n}/pod-logs?ns=${ns}&pod=${pod}&container=${ctr}&lines=${lines}`, null, 'text'),
    testStorage:     (n)    => request('POST',   `/clusters/${n}/test-storage`),
    scaleCluster:    (n, w) => request('PATCH',  `/clusters/${n}/scale`, { worker_count: w }),
    upgradeCluster:  (n, v) => request('PATCH',  `/clusters/${n}/upgrade`, { k8s_version: v }),
    getKubeconfig: async (n) => {
        const res = await fetch(`${API}/clusters/${n}/kubeconfig`, {
            headers: { Authorization: 'Bearer ' + token() }
        });
        return res.text();
    },
    getVersions:     ()     => request('GET', '/templates/k8s-versions'),
    getFlavors:      ()     => request('GET', '/templates/flavors'),
    // Cluster templates
    listTemplates:   ()     => request('GET',    '/cluster-templates/'),
    createTemplate:  (b)    => request('POST',   '/cluster-templates/',  b),
    deleteTemplate:  (id)   => request('DELETE', `/cluster-templates/${id}`),
    // Admin
    listUsers:       ()     => request('GET', '/admin/users'),
    listTenants:     ()     => request('GET', '/tenants/'),
    assignTenant:    (tid, uid) => request('POST', `/tenants/${tid}/assign?user_id=${uid}`),
    getAuditLog:     ()     => request('GET', '/admin/audit'),
};

function logout() {
    localStorage.removeItem('token');
    window.location.href = '/login';
}

function badge(status) {
    const map = { Ready: 'ready', Provisioning: 'provisioning', Failed: 'error', Deleting: 'provisioning' };
    const cls = map[status] || 'default';
    return `<span class="badge badge-${cls}">${status || 'Unknown'}</span>`;
}

async function loadNavUser({ checkTenant = false } = {}) {
    try {
        const user = await api.me();
        const el = document.getElementById('nav-user');
        if (el) el.textContent = user.username;
        if (checkTenant && !user.tenant_id) {
            window.location.href = '/setup';
        }
        // Show admin nav links if user is admin
        if (user.is_admin) {
            document.querySelectorAll('.nav-admin').forEach(el => el.style.display = '');
        }
    } catch {}
}
