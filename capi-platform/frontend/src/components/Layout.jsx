import { useContext } from "react";
import { AuthCtx } from "../App";

const s = {
  shell:   { display:"flex", minHeight:"100vh", fontFamily:"system-ui,sans-serif" },
  sidebar: { width:220, background:"#1e1e2e", color:"#cdd6f4", display:"flex", flexDirection:"column", padding:"24px 0" },
  brand:   { fontSize:15, fontWeight:600, padding:"0 20px 24px", color:"#cba6f7" },
  navBtn:  { background:"none", border:"none", color:"#cdd6f4", textAlign:"left", padding:"10px 20px", cursor:"pointer", fontSize:14, width:"100%" },
  navAct:  { background:"#313244", color:"#cba6f7" },
  main:    { flex:1, background:"#f8f8fc", overflow:"auto" },
  topbar:  { background:"#fff", borderBottom:"1px solid #e2e8f0", padding:"12px 24px", display:"flex", justifyContent:"space-between", alignItems:"center" },
  content: { padding:"24px" },
  logoutBtn:{ background:"none", border:"1px solid #e2e8f0", borderRadius:6, padding:"6px 12px", cursor:"pointer", fontSize:13 },
};

export default function Layout({ nav, page, children }) {
  const { user, logout } = useContext(AuthCtx);
  const navItem = (label, p) => (
    <button key={p} style={{...s.navBtn, ...(page===p?s.navAct:{})}} onClick={() => nav(p)}>{label}</button>
  );
  return (
    <div style={s.shell}>
      <aside style={s.sidebar}>
        <div style={s.brand}>⎈ CAPI Platform</div>
        {navItem("Dashboard", "dashboard")}
        {navItem("Nouveau cluster", "wizard")}
      </aside>
      <div style={s.main}>
        <div style={s.topbar}>
          <span style={{fontSize:14,color:"#64748b"}}>Connecté : <strong>{user.username}</strong></span>
          <button style={s.logoutBtn} onClick={logout}>Déconnexion</button>
        </div>
        <div style={s.content}>{children}</div>
      </div>
    </div>
  );
}
