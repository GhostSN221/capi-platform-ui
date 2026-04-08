import { useEffect, useState } from "react";
import { api } from "../api/client";
import ClusterCard from "../components/ClusterCard";
const s = {
  header:{ display:"flex", justifyContent:"space-between", alignItems:"center", marginBottom:24 },
  title: { fontSize:22, fontWeight:600, color:"#1e1e2e" },
  btn:   { background:"#7c3aed", color:"#fff", border:"none", borderRadius:8, padding:"8px 18px", cursor:"pointer", fontSize:14, fontWeight:500 },
  grid:  { display:"grid", gridTemplateColumns:"repeat(auto-fill, minmax(300px,1fr))", gap:16 },
  empty: { color:"#94a3b8", textAlign:"center", marginTop:60, fontSize:15 },
};
export default function Dashboard({ nav }) {
  const [clusters, setClusters] = useState([]);
  const load = () => api.listClusters().then(setClusters).catch(console.error);
  useEffect(() => { load(); const id=setInterval(load,15000); return ()=>clearInterval(id); }, []);
  const del = async n => { if(!confirm(`Supprimer "${n}" ?`)) return; await api.deleteCluster(n); load(); };
  return (
    <div>
      <div style={s.header}>
        <span style={s.title}>Clusters ({clusters.length})</span>
        <button style={s.btn} onClick={()=>nav("wizard")}>+ Nouveau cluster</button>
      </div>
      {clusters.length===0
        ? <div style={s.empty}>Aucun cluster. Créez-en un !</div>
        : <div style={s.grid}>{clusters.map(c=><ClusterCard key={c.id} cluster={c} onClick={()=>nav("detail",c.name)} onDelete={del}/>)}</div>
      }
    </div>
  );
}
