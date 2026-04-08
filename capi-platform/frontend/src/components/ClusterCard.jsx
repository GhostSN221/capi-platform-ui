import StatusBadge from "./StatusBadge";
const s = {
  card:{ background:"#fff", borderRadius:10, border:"1px solid #e2e8f0", padding:20, cursor:"pointer" },
  name:{ fontSize:16, fontWeight:600, color:"#1e1e2e", marginBottom:6 },
  meta:{ fontSize:13, color:"#64748b" },
  row: { display:"flex", justifyContent:"space-between", alignItems:"center", marginBottom:8 },
};
export default function ClusterCard({ cluster, onClick, onDelete }) {
  return (
    <div style={s.card} onClick={onClick}>
      <div style={s.row}>
        <span style={s.name}>{cluster.name}</span>
        <StatusBadge status={cluster.status} />
      </div>
      <div style={s.meta}>Version : {cluster.k8s_version} · Workers : {cluster.worker_count}</div>
      <div style={{...s.meta, marginTop:4}}>Créé le {new Date(cluster.created_at).toLocaleDateString("fr-FR")}</div>
      <button onClick={e=>{e.stopPropagation();onDelete(cluster.name);}}
        style={{marginTop:12,background:"none",border:"1px solid #fca5a5",color:"#dc2626",borderRadius:6,padding:"4px 10px",fontSize:12,cursor:"pointer"}}>
        Supprimer
      </button>
    </div>
  );
}
