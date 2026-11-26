from decimal import Decimal, InvalidOperation
import re

def parse_vnd(value: str | None) -> Decimal | None:
    if value is None:
        return None
    s = str(value).strip().replace("VND", "").replace("₫", "").replace("đ", "")
    s = re.sub(r"\s+", "", s)
    if not s:
        return None
    # Vietnamese exports commonly use dot as thousands separator.
    if "," in s and "." in s:
        s = s.replace(".", "").replace(",", ".")
    elif "," in s:
        # Treat comma as decimal separator only when exactly two trailing digits.
        parts = s.split(",")
        s = "".join(parts[:-1]) + ("." + parts[-1] if len(parts[-1]) == 2 else parts[-1])
    else:
        s = s.replace(".", "")
    try:
        return Decimal(s)
    except InvalidOperation:
        return None

def normalize_date(value: str | None) -> str | None:
    if not value:
        return None
    value = value.strip()
    for fmt in ("%d/%m/%Y", "%d-%m-%Y", "%Y-%m-%d"):
        from datetime import datetime
        try:
            return datetime.strptime(value, fmt).date().isoformat()
        except ValueError:
            pass
    return None
