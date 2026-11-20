import React, { useState } from "react";

// This form calls the team's Spring Boot API, never DATA-AI directly.
export default function CustomerApplicationForm() {
  const [form, setForm] = useState({
    fullName: "", phone: "", email: "", dateOfBirth: "",
    gender: "", identityType: "CCCD", identityLast4: "", maritalStatus: "",
    dependentsCount: 0, address: "", province: "", employmentType: "SALARIED",
    employerName: "", jobTitle: "", monthlyIncome: "", requestedAmount: "",
    requestedTermMonths: 12, loanPurpose: "", consent: false,
  });
  const [message, setMessage] = useState("");
  const change = (key: string, value: string | number | boolean) => setForm(old => ({ ...old, [key]: value }));
  const submit = async (event: React.FormEvent) => {
    event.preventDefault(); setMessage("Đang gửi hồ sơ...");
    const response = await fetch("/api/customer-applications", {
      method: "POST", credentials: "include", headers: { "Content-Type": "application/json" },
      body: JSON.stringify(form),
    });
    if (!response.ok) { setMessage(`Không gửi được hồ sơ (${response.status})`); return; }
    const result = await response.json(); setMessage(`Đã tiếp nhận hồ sơ: ${result.applicationCode ?? result.caseId ?? "thành công"}`);
  };
  const field = (label: string, key: keyof typeof form, type = "text", required = false) => (
    <label style={{ display: "grid", gap: 6 }}>
      <span>{label}{required ? " *" : ""}</span>
      <input type={type} required={required} value={String(form[key])}
        onChange={e => change(key, type === "number" ? Number(e.target.value) : e.target.value)} />
    </label>
  );
  return <form onSubmit={submit} style={{ maxWidth: 760, margin: "24px auto", display: "grid", gap: 16 }}>
    <h2>Thông tin đăng ký vay</h2>
    <h3>Thông tin cá nhân</h3>
    {field("Họ và tên", "fullName", "text", true)}
    {field("Ngày sinh", "dateOfBirth", "date", true)}
    {field("Số điện thoại", "phone", "tel", true)}
    {field("Email", "email", "email")}
    {field("4 số cuối giấy tờ định danh", "identityLast4")}
    <label>Giới tính<select value={form.gender} onChange={e => change("gender", e.target.value)}><option value="">Chọn</option><option>MALE</option><option>FEMALE</option><option>OTHER</option></select></label>
    <label>Tình trạng hôn nhân<select value={form.maritalStatus} onChange={e => change("maritalStatus", e.target.value)}><option value="">Chọn</option><option>SINGLE</option><option>MARRIED</option><option>OTHER</option></select></label>
    {field("Số người phụ thuộc", "dependentsCount", "number")}
    <h3>Địa chỉ</h3>
    {field("Địa chỉ cụ thể", "address", "text", true)}{field("Tỉnh/thành phố", "province", "text", true)}
    <h3>Công việc và thu nhập tự khai báo</h3>
    <label>Loại công việc<select value={form.employmentType} onChange={e => change("employmentType", e.target.value)}><option value="SALARIED">Làm công hưởng lương</option><option value="SELF_EMPLOYED">Tự kinh doanh</option><option value="CONTRACT">Hợp đồng</option><option value="OTHER">Khác</option></select></label>
    {field("Tên công ty", "employerName")}{field("Chức danh", "jobTitle")}{field("Thu nhập hàng tháng (VND)", "monthlyIncome", "number", true)}
    <h3>Nhu cầu vay</h3>
    {field("Số tiền đề nghị (VND)", "requestedAmount", "number", true)}
    {field("Thời hạn (tháng)", "requestedTermMonths", "number", true)}
    <label>Mục đích vay<textarea required value={form.loanPurpose} onChange={e => change("loanPurpose", e.target.value)} /></label>
    <label><input type="checkbox" checked={form.consent} onChange={e => change("consent", e.target.checked)} required /> Tôi xác nhận thông tin đã khai và đồng ý xử lý dữ liệu theo thông báo của ngân hàng.</label>
    <button type="submit">Gửi hồ sơ</button><p role="status">{message}</p>
  </form>;
}
