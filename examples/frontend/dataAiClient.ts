// Frontend must call Spring Boot, not this DATA-AI service directly.
// Spring Boot should proxy these routes after authenticating the signed-in user.
export type DataAiDocument = {
  id: string; case_id: string; original_filename: string; sha256: string;
  document_type: string; layout_code: string; evidence_status: string;
  processing_status: string; page_count: number;
};

export async function uploadEvidence(caseId: string, file: File): Promise<DataAiDocument> {
  const form = new FormData();
  form.append("file", file);
  const response = await fetch(`/api/cases/${caseId}/evidence`, {
    method: "POST", body: form, credentials: "include",
  });
  if (!response.ok) throw new Error(`Upload failed (${response.status})`);
  return response.json();
}

export async function getEvidence(caseId: string): Promise<DataAiDocument[]> {
  const response = await fetch(`/api/cases/${caseId}/evidence`, { credentials: "include" });
  if (!response.ok) throw new Error(`Load evidence failed (${response.status})`);
  return response.json();
}

// Customer form is posted to the authenticated Spring Boot API. The backend
// persists the canonical application and forwards the approved DATA-AI snapshot.
export async function submitApplicantForm(caseId: string, form: Record<string, unknown>) {
  const response = await fetch(`/api/cases/${caseId}/applicant-form`, {
    method: "POST",
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(form),
  });
  if (!response.ok) throw new Error(`Submit applicant form failed (${response.status})`);
  return response.json();
}

// Staff-only route implemented by Spring Boot. Never call DATA-AI directly
// from a browser and never expose X-Internal-Service-Token to the frontend.
export async function downloadDataAiExcel(caseId?: string): Promise<void> {
  const query = caseId ? `?case_id=${encodeURIComponent(caseId)}` : "";
  const response = await fetch(`/api/staff/data-exports/excel${query}`, {
    method: "GET", credentials: "include",
  });
  if (!response.ok) throw new Error(`Excel export failed (${response.status})`);
  const blob = await response.blob();
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = "data_ai_export.xlsx";
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(url);
}
