def classify_transaction(description: str, amount: float | None, direction: str):
    """Rule-based suggestion only. Never treats every incoming credit as salary."""
    if direction.upper() != "CREDIT":
        return "not_credit", 0.99, False
    text = (description or "").lower()
    rules = [
        (("hoan tien", "hoàn tiền", "refund", "reversal", "tra lai"), "reversal", 0.90, False),
        (("vay", "giai ngan", "giải ngân", "loan", "disbursement"), "borrowing", 0.88, False),
        (("chuyen tien", "chuyển tiền", "ck noi bo", "transfer", "nap tien"), "transfer", 0.78, False),
        (("hoan ung", "hoàn ứng", "reimbursement", "cong tac phi"), "reimbursement", 0.82, False),
        (("thuong", "thưởng", "bonus", "thang 13", "tháng 13"), "variable_pay", 0.82, False),
        (("luong", "lương", "salary", "payroll"), "salary_candidate", 0.86, False),
    ]
    for keywords, category, confidence, eligible in rules:
        if any(k in text for k in keywords):
            return category, confidence, eligible
    return "unknown", 0.25, False
