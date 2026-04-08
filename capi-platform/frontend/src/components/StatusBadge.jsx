const C = {
  Provisioned:  { bg:"#dcfce7", color:"#166534" },
  Provisioning: { bg:"#fef9c3", color:"#854d0e" },
  Deleting:     { bg:"#fee2e2", color:"#991b1b" },
  Failed:       { bg:"#fee2e2", color:"#991b1b" },
  Unknown:      { bg:"#f1f5f9", color:"#475569" },
};
export default function StatusBadge({ status }) {
  const c = C[status] || C.Unknown;
  return <span style={{...c, borderRadius:999, padding:"2px 10px", fontSize:12, fontWeight:500}}>{status}</span>;
}
