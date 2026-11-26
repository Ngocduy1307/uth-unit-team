import React, { useState } from "react";

// Public browser calls Spring Boot only. Spring Boot authenticates the customer,
// validates ownership/consent, maps this DTO and calls DATA-AI internally.
export default function CustomerApplicationForm() {
  const [form, setForm] = useState({
    fullName: "",
    dateOfBirth: "",
    phone: "",
    email: "",
    residencyDeclaration: false,
    province: "",
    ward: "",
    address: "",
    employerName: "",
    jobTitle: "",
    monthlyIncome: "",
    incomeType: "NET",
    salaryPaidToBank: false,
    requestedAmount: "",
    requestedTermMonths: 12,
    loanPurpose: "",
    consent: false,
  });
  const [message, setMessage] = useState("");
  const [submitting, setSubmitting] = useState(false);

  const change = (key: keyof typeof form, value: string | number | boolean) =>
    setForm(old => ({ ...old, [key]: value }));

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!form.residencyDeclaration || !form.salaryPaidToBank || !form.consent) {
      setMessage("Vui lòng hoàn tất các xác nhận bắt buộc.");
      return;
    }
    if (Number(form.requestedTermMonths) < 6 || Number(form.requestedTermMonths) > 36) {
      setMessage("Thời hạn vay phải từ 6 đến 36 tháng.");
      return;
    }

    setSubmitting(true);
    setMessage("Đang gửi hồ sơ...");
    try {
      const response = await fetch("/api/customer-applications", {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          ...form,
          employmentType: "SALARIED",
          incomeBasis: form.incomeType,
          monthlyIncome: form.monthlyIncome === "" ? null : form.monthlyIncome,
          requestedAmount: form.requestedAmount,
          requestedTermMonths: Number(form.requestedTermMonths),
          formVersion: "1.1",
        }),
      });
      if (!response.ok) {
        setMessage(`Không gửi được hồ sơ (${response.status}). Vui lòng thử lại hoặc liên hệ hỗ trợ.`);
        return;
      }
      const result = await response.json();
      setMessage(`Đã tiếp nhận hồ sơ: ${result.applicationCode ?? result.caseId ?? "thành công"}`);
    } catch {
      setMessage("Không thể kết nối máy chủ. Vui lòng kiểm tra kết nối và thử lại.");
    } finally {
      setSubmitting(false);
    }
  };

  const field = (
    label: string,
    key: keyof typeof form,
    type = "text",
    required = false,
    hint?: string,
  ) => (
    <label style={{ display: "grid", gap: 6 }}>
      <span>{label}{required ? " *" : ""}</span>
      <input
        type={type}
        required={required}
        min={key === "requestedTermMonths" ? 6 : undefined}
        max={key === "requestedTermMonths" ? 36 : undefined}
        minLength={key === "fullName" ? 2 : undefined}
        step={type === "number" ? "1" : undefined}
        value={String(form[key])}
        onChange={e => change(key, type === "number"
          ? (e.target.value === "" ? "" : Number(e.target.value))
          : e.target.value)}
      />
      {hint && <small style={{ color: "#666" }}>{hint}</small>}
    </label>
  );

  return (
    <form onSubmit={submit} style={{ maxWidth: 760, margin: "24px auto", display: "grid", gap: 16 }}>
      <h2>Đăng ký nhu cầu vay</h2>
      <p>Biểu mẫu ban đầu chỉ thu thập thông tin cần thiết để mở hồ sơ. Ngân hàng có thể yêu cầu chứng từ hoặc kê khai bổ sung sau.</p>

      <h3>1. Thông tin cá nhân</h3>
      {field("Họ và tên theo giấy tờ", "fullName", "text", true)}
      {field("Ngày sinh", "dateOfBirth", "date", true)}
      {field("Số điện thoại", "phone", "tel", true)}
      {field("Email", "email", "email", false)}
      <label style={{ display: "flex", gap: 8, alignItems: "flex-start" }}>
        <input type="checkbox" checked={form.residencyDeclaration}
          onChange={e => change("residencyDeclaration", e.target.checked)} required />
        Tôi xác nhận là cá nhân cư trú tại Việt Nam.
      </label>

      <h3>2. Địa chỉ hiện tại</h3>
      {field("Tỉnh / thành phố", "province", "text", true)}
      {field("Phường / xã", "ward", "text", true)}
      {field("Số nhà, tên đường", "address", "text", false)}

      <h3>3. Công việc và thu nhập</h3>
      {field("Tên công ty / đơn vị đang làm việc", "employerName", "text", true)}
      {field("Chức danh", "jobTitle", "text", false)}
      {field("Thu nhập hàng tháng khai báo (VND)", "monthlyIncome", "number", true)}
      <label style={{ display: "grid", gap: 6 }}>
        <span>Thu nhập khai báo là *</span>
        <select required value={form.incomeType}
          onChange={e => change("incomeType", e.target.value)}>
          <option value="NET">Thực nhận (Net)</option>
          <option value="GROSS">Trước khấu trừ (Gross)</option>
        </select>
      </label>
      <label style={{ display: "flex", gap: 8, alignItems: "flex-start" }}>
        <input type="checkbox" checked={form.salaryPaidToBank}
          onChange={e => change("salaryPaidToBank", e.target.checked)} required />
        Tôi xác nhận nhận lương qua tài khoản ngân hàng.
      </label>
      <small style={{ color: "#666" }}>
        Số tiền khai báo chỉ là thông tin tham khảo, chưa phải thu nhập ròng hợp lệ. Ngân hàng sẽ đối chiếu bảng lương và sao kê 6 tháng.
      </small>

      <h3>4. Nhu cầu vay</h3>
      {field("Số tiền đề nghị vay (VND)", "requestedAmount", "number", true)}
      {field("Thời hạn vay (6–36 tháng)", "requestedTermMonths", "number", true)}
      <label style={{ display: "grid", gap: 6 }}>
        <span>Mục đích vay *</span>
        <textarea required maxLength={500} value={form.loanPurpose}
          onChange={e => change("loanPurpose", e.target.value)} />
      </label>

      <h3>5. Xác nhận</h3>
      <label style={{ display: "flex", gap: 8, alignItems: "flex-start" }}>
        <input type="checkbox" checked={form.consent}
          onChange={e => change("consent", e.target.checked)} required />
        Tôi xác nhận thông tin đã khai là trung thực và đồng ý việc xử lý dữ liệu theo thông báo và cơ chế đồng ý của ngân hàng.
      </label>
      <small style={{ color: "#666" }}>
        Không nhập số CCCD đầy đủ, số tài khoản ngân hàng đầy đủ hoặc mật khẩu tại biểu mẫu này.
        Thông tin chi phí, nghĩa vụ nợ và chứng từ chi tiết sẽ được bổ sung ở bước riêng khi cần.
      </small>
      <button type="submit" disabled={submitting}>{submitting ? "Đang gửi..." : "Gửi hồ sơ"}</button>
      <p role="status">{message}</p>
    </form>
  );
}
