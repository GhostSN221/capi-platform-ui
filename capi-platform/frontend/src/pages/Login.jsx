import { useState } from "react";
import { api } from "../api/client";
const s = {
  wrap: { minHeight:"100vh", display:"flex", alignItems:"center", justifyContent:"center", background:"#f1f5f9" },
  card: { background:"#fff", borderRadius:12, padding:40, width:360, boxShadow:"0 4px 24px #0001" },
  title:{ fontSize:22, fontWeight:600, marginBottom:24, color:"#1e1e2e" },
  label:{ fontSize:13, color:"#64748b", display:"block", marginBottom:4 },
  input:{ width:"100%", padding:"8px 12px", borderRadius:6, border:"1px solid #e2e8f0", fontSize:14, boxSizing:"border-box", marginBottom:16 },
  btn:  { width:"100%", padding:"10px", background:"#7c3aed", color:"#fff", border:"none", borderRadius:6, fontSize:14, cursor:"pointer", fontWeight:500 },
  err:  { color:"#dc2626", fontSize:13, marginTop:8 },
};
export default function Login({ onLogin }) {
  const [u,setU]=useState(""); const [p,setP]=useState(""); const [err,setErr]=useState("");
  const submit = async () => {
    try {
      const { access_token } = await api.login(u, p);
      localStorage.setItem("token", access_token);
      onLogin(await api.me());
    } catch { setErr("Identifiants invalides"); }
  };
  return (
    <div style={s.wrap}><div style={s.card}>
      <div style={s.title}>⎈ CAPI Platform</div>
      <label style={s.label}>Utilisateur</label>
      <input style={s.input} value={u} onChange={e=>setU(e.target.value)} />
      <label style={s.label}>Mot de passe</label>
      <input style={s.input} type="password" value={p} onChange={e=>setP(e.target.value)} onKeyDown={e=>e.key==="Enter"&&submit()} />
      <button style={s.btn} onClick={submit}>Se connecter</button>
      {err && <div style={s.err}>{err}</div>}
    </div></div>
  );
}
