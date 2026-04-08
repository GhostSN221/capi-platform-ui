import { useEffect, useState } from "react";
import { api } from "../api/client";
const s = {
  card:  { background:"#fff", borderRadius:12, border:"1px solid #e2e8f0", padding:32, maxWidth:560 },
  title: { fontSize:18, fontWeight:600, marginBottom:24, color:"#1e1e2e" },
  label: { fontSize:13, color:"#64748b", display:"block", marginBottom:4, marginTop:16 },
  input: { width:"100%", padding:"8px 12px", borderRadius:6, border:"1px solid #e2e8f0", fontSize:14, boxSizing:"border-box" },
  sel:   { width:"100%", padding:"8px 12px", borderRadius:6, border:"1px solid #e2e8f0", fontSize:14, boxSizing:"border-box", background:"#fff" },
  row:   { display:"flex", gap:16 },
  btnRow:{ display:"flex", gap:12, marginTop:28 },
  btn:   { flex:1, padding:"10px", background:"#7c3aed", color:"#fff", border:"none", borderRadius:8, cursor:"pointer", fontSize:14, fontWeight:500 },
  cancel:{ flex:1, padding:"10px", background:"#f1f5f9", color:"#475569", border:"none", borderRadius:8, cursor:"pointer", fontSize:14 },
  steps: { display:"flex", gap:8, marginBottom:24 },
  step:  { flex:1, height:4, borderRadius:2, background:"#e2e8f0" },
  stepA: { background:"#7c3aed" },
  err:   { color:"#dc2626", fontSize:13, marginTop:12 },
};
export default function ClusterWizard({ nav }) {
  const [step,setStep]=useState(0);
  const [versions,setVersions]=useState([]); const [flavors,setFlavors]=useState([]);
  const [form,setForm]=useState({name:"",k8s_version:"",cp_flavor:"",worker_flavor:"",worker_count:3});
  const [loading,setLoading]=useState(false); const [err,setErr]=useState("");
  useEffect(()=>{ api.getVersions().then(setVersions); api.getFlavors().then(setFlavors); },[]);
  const set=(k,v)=>setForm(f=>({...f,[k]:v}));
  const submit=async()=>{ setLoading(true); setErr(""); try{ await api.createCluster(form); nav("dashboard"); } catch(e){ setErr(String(e)); } finally{ setLoading(false); } };
  return (
    <div>
      <h2 style={{fontSize:22,fontWeight:600,color:"#1e1e2e",marginBottom:20}}>Nouveau cluster</h2>
      <div style={s.card}>
        <div style={s.steps}>{[0,1,2].map(i=><div key={i} style={{...s.step,...(step>=i?s.stepA:{})}}/>)}</div>
        {step===0 && <>
          <div style={s.title}>1. Informations générales</div>
          <label style={s.label}>Nom du cluster</label>
          <input style={s.input} placeholder="ex: client-alpha-prod" value={form.name} onChange={e=>set("name",e.target.value)}/>
          <label style={s.label}>Version Kubernetes</label>
          <select style={s.sel} value={form.k8s_version} onChange={e=>set("k8s_version",e.target.value)}>
            <option value="">-- choisir --</option>{versions.map(v=><option key={v}>{v}</option>)}
          </select>
        </>}
        {step===1 && <>
          <div style={s.title}>2. Dimensionnement</div>
          <div style={s.row}>
            <div style={{flex:1}}>
              <label style={s.label}>Flavor control plane</label>
              <select style={s.sel} value={form.cp_flavor} onChange={e=>set("cp_flavor",e.target.value)}>
                <option value="">-- choisir --</option>{flavors.map(f=><option key={f}>{f}</option>)}
              </select>
            </div>
            <div style={{flex:1}}>
              <label style={s.label}>Flavor workers</label>
              <select style={s.sel} value={form.worker_flavor} onChange={e=>set("worker_flavor",e.target.value)}>
                <option value="">-- choisir --</option>{flavors.map(f=><option key={f}>{f}</option>)}
              </select>
            </div>
          </div>
          <label style={s.label}>Nombre de workers</label>
          <input style={s.input} type="number" min={1} max={20} value={form.worker_count} onChange={e=>set("worker_count",parseInt(e.target.value))}/>
        </>}
        {step===2 && <>
          <div style={s.title}>3. Confirmation</div>
          {[["Nom",form.name],["Version",form.k8s_version],["CP flavor",form.cp_flavor],["Worker flavor",form.worker_flavor],["Nb workers",form.worker_count]].map(([k,v])=>(
            <div key={k} style={{display:"flex",justifyContent:"space-between",padding:"8px 0",borderBottom:"1px solid #f1f5f9",fontSize:14}}>
              <span style={{color:"#64748b"}}>{k}</span><span style={{fontWeight:500}}>{v}</span>
            </div>
          ))}
        </>}
        {err && <div style={s.err}>{err}</div>}
        <div style={s.btnRow}>
          <button style={s.cancel} onClick={()=>step>0?setStep(step-1):nav("dashboard")}>{step===0?"Annuler":"Précédent"}</button>
          {step<2
            ? <button style={s.btn} onClick={()=>setStep(step+1)} disabled={step===0&&(!form.name||!form.k8s_version)}>Suivant →</button>
            : <button style={s.btn} onClick={submit} disabled={loading}>{loading?"Création…":"Créer le cluster"}</button>
          }
        </div>
      </div>
    </div>
  );
}
