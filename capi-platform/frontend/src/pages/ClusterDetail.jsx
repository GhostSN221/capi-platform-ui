import { useEffect, useState } from "react";
import { api } from "../api/client";
import StatusBadge from "../components/StatusBadge";
const s = {
  back: { background:"none",border:"none",color:"#7c3aed",cursor:"pointer",fontSize:14,marginBottom:16,padding:0 },
  title:{ fontSize:20,fontWeight:600,color:"#1e1e2e",marginBottom:4 },
  sh:   { fontSize:15,fontWeight:600,color:"#1e1e2e",marginBottom:12,marginTop:24 },
  table:{ width:"100%",borderCollapse:"collapse",fontSize:14,background:"#fff",borderRadius:8,overflow:"hidden",border:"1px solid #e2e8f0" },
  th:   { padding:"10px 14px",textAlign:"left",fontSize:12,color:"#64748b",background:"#f8fafc",borderBottom:"1px solid #e2e8f0" },
  td:   { padding:"10px 14px",borderBottom:"1px solid #f1f5f9" },
  kbtn: { background:"#f1f5f9",border:"none",borderRadius:6,padding:"6px 12px",cursor:"pointer",fontSize:13,marginTop:12 },
};
export default function ClusterDetail({ name, nav }) {
  const [machines,setMachines]=useState([]);
  useEffect(()=>{
    api.getMachines(name).then(setMachines).catch(console.error);
    const id=setInterval(()=>api.getMachines(name).then(setMachines),10000);
    return ()=>clearInterval(id);
  },[name]);
  const downloadKubeconfig=async()=>{
    const kc=await api.getKubeconfig(name);
    const a=document.createElement("a");
    a.href=URL.createObjectURL(new Blob([kc],{type:"text/yaml"}));
    a.download=`${name}-kubeconfig.yaml`; a.click();
  };
  return (
    <div>
      <button style={s.back} onClick={()=>nav("dashboard")}>← Retour</button>
      <div style={s.title}>{name}</div>
      <button style={s.kbtn} onClick={downloadKubeconfig}>⬇ Télécharger kubeconfig</button>
      <div style={s.sh}>Machines ({machines.length})</div>
      <table style={s.table}>
        <thead><tr>
          <th style={s.th}>Nom</th><th style={s.th}>Phase</th><th style={s.th}>Prêt</th><th style={s.th}>Flavor</th>
        </tr></thead>
        <tbody>
          {machines.map(m=>(
            <tr key={m.name}>
              <td style={s.td}>{m.name}</td>
              <td style={s.td}><StatusBadge status={m.phase}/></td>
              <td style={s.td}>{m.ready?"✓":"—"}</td>
              <td style={s.td}>{m.flavor}</td>
            </tr>
          ))}
          {machines.length===0&&<tr><td colSpan={4} style={{...s.td,color:"#94a3b8",textAlign:"center"}}>Aucune machine</td></tr>}
        </tbody>
      </table>
    </div>
  );
}
