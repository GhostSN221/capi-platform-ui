import { useState, useEffect, createContext, useContext } from "react";
import { api } from "./api/client";
import Login from "./pages/Login";
import Dashboard from "./pages/Dashboard";
import ClusterWizard from "./pages/ClusterWizard";
import ClusterDetail from "./pages/ClusterDetail";
import Layout from "./components/Layout";

export const AuthCtx = createContext(null);

export default function App() {
  const [user, setUser]       = useState(null);
  const [page, setPage]       = useState("dashboard");
  const [pageArg, setPageArg] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => { api.me().then(setUser).catch(() => {}).finally(() => setLoading(false)); }, []);

  const nav    = (p, arg = null) => { setPage(p); setPageArg(arg); };
  const logout = () => { localStorage.removeItem("token"); setUser(null); };

  if (loading) return <div style={{display:"flex",justifyContent:"center",alignItems:"center",height:"100vh",fontFamily:"system-ui"}}>Chargement…</div>;
  if (!user)   return <Login onLogin={u => setUser(u)} />;

  return (
    <AuthCtx.Provider value={{ user, logout }}>
      <Layout nav={nav} page={page}>
        {page === "dashboard" && <Dashboard nav={nav} />}
        {page === "wizard"    && <ClusterWizard nav={nav} />}
        {page === "detail"    && <ClusterDetail name={pageArg} nav={nav} />}
      </Layout>
    </AuthCtx.Provider>
  );
}
