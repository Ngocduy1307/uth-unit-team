from pathlib import Path
import fitz
from PIL import Image
import pytesseract
from pytesseract import Output
from app.config import settings

ALLOWED = {".pdf", ".jpg", ".jpeg", ".png"}

def read_pages(path: Path):
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        doc = fitz.open(path)
        if doc.page_count > settings.max_pdf_pages:
            raise ValueError(f"PDF có {doc.page_count} trang, vượt giới hạn {settings.max_pdf_pages}.")
        for index, page in enumerate(doc):
            pix = page.get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False)
            image = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
            yield index + 1, image
    elif suffix in {".jpg", ".jpeg", ".png"}:
        yield 1, Image.open(path).convert("RGB")
    else:
        raise ValueError("OCR chỉ hỗ trợ PDF/JPG/JPEG/PNG.")

def extract_words(path: Path):
    words = []
    page_count = 0
    for page_number, image in read_pages(path):
        page_count = page_number
        data = pytesseract.image_to_data(image, lang=settings.ocr_lang, output_type=Output.DICT)
        for i, raw in enumerate(data["text"]):
            token = (raw or "").strip()
            if not token:
                continue
            try:
                confidence = max(0.0, min(1.0, float(data["conf"][i]) / 100))
            except (ValueError, TypeError):
                confidence = 0.0
            words.append({
                "text": token, "confidence": confidence, "page_number": page_number,
                "bbox": {"x": int(data["left"][i]), "y": int(data["top"][i]),
                         "width": int(data["width"][i]), "height": int(data["height"][i])}
            })
    return words, page_count
