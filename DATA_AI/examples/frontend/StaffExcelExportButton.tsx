import React, { useState } from "react";

// Spring Boot checks the signed-in staff role and bank scope before calling DATA-AI.
export function StaffExcelExportButton({ caseId }: { caseId?: string }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const download = async () => {
    setBusy(true); setError("");
    try {
      const query = caseId ? `?case_id=${encodeURIComponent(caseId)}` : "";
      const response = await fetch(`/api/staff/data-exports/excel${query}`, { credentials: "include" });
      if (!response.ok) throw new Error(`Export failed (${response.status})`);
      const blob = await response.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a"); a.href = url; a.download = "data_ai_customer_and_evidence.xlsx";
      document.body.appendChild(a); a.click(); a.remove(); URL.revokeObjectURL(url);
    } catch (e) { setError(e instanceof Error ? e.message : "Export failed"); }
    finally { setBusy(false); }
  };
  return <div><button type="button" disabled={busy} onClick={download}>{busy ? "Đang xuất..." : "Xuất Excel dữ liệu"}</button>{error && <p role="alert">{error}</p>}</div>;
}
