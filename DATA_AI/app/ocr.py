"""PDF/image text extraction with source anchors.

Digital PDF pages use their embedded text layer first. Scanned or sparse pages
fall back to Tesseract. Coordinates are expressed in page pixels for raster OCR
and PDF points for native text; `coordinate_space` makes the distinction explicit.
"""
from pathlib import Path
import fitz
from PIL import Image, ImageOps
import pytesseract
from pytesseract import Output
from app.config import settings

ALLOWED = {".pdf", ".jpg", ".jpeg", ".png"}


def _native_pdf_words(page, page_number: int):
    words = []
    for item in page.get_text("words", sort=True):
        x0, y0, x1, y1, token = item[:5]
        token = (token or "").strip()
        if not token:
            continue
        words.append({
            "text": token,
            "confidence": 1.0,  # embedded text, not an OCR confidence score
            "page_number": page_number,
            "bbox": {"x": round(x0, 2), "y": round(y0, 2),
                     "width": round(x1 - x0, 2), "height": round(y1 - y0, 2)},
            "coordinate_space": "PDF_POINT",
            "extraction_method": "PDF_TEXT_LAYER",
        })
    return words


def _ocr_image(image: Image.Image, page_number: int):
    # Normalize orientation metadata and ensure a predictable RGB image.
    image = ImageOps.exif_transpose(image).convert("RGB")
    data = pytesseract.image_to_data(image, lang=settings.ocr_lang, output_type=Output.DICT)
    words = []
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
                     "width": int(data["width"][i]), "height": int(data["height"][i])},
            "coordinate_space": "IMAGE_PIXEL",
            "extraction_method": "TESSERACT_OCR",
            "block_num": int(data["block_num"][i]),
            "par_num": int(data["par_num"][i]),
            "line_num": int(data["line_num"][i]),
        })
    return words


def read_pages(path: Path):
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        try:
            doc = fitz.open(path)
        except Exception as exc:
            raise ValueError("PDF không hợp lệ hoặc không thể mở.") from exc
        try:
            if doc.is_encrypted:
                raise ValueError("PDF được mã hóa/mật khẩu; cần xử lý theo quy trình được phép.")
            if doc.page_count == 0:
                raise ValueError("PDF không có trang.")
            if doc.page_count > settings.max_pdf_pages:
                raise ValueError(f"PDF có {doc.page_count} trang, vượt giới hạn {settings.max_pdf_pages}.")
            for index, page in enumerate(doc):
                page_number = index + 1
                native_words = _native_pdf_words(page, page_number)
                # Prefer the native text layer; OCR only scanned/sparse pages.
                if len(native_words) >= 3:
                    yield page_number, native_words
                    continue
                pix = page.get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False)
                image = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
                yield page_number, _ocr_image(image, page_number)
        finally:
            doc.close()
    elif suffix in {".jpg", ".jpeg", ".png"}:
        try:
            with Image.open(path) as source:
                source.verify()
            with Image.open(path) as source:
                image = ImageOps.exif_transpose(source).convert("RGB")
        except Exception as exc:
            raise ValueError("Ảnh không hợp lệ hoặc không thể giải mã.") from exc
        yield 1, _ocr_image(image, 1)
    else:
        raise ValueError("OCR chỉ hỗ trợ PDF/JPG/JPEG/PNG.")


def extract_words(path: Path):
    words = []
    page_count = 0
    for page_number, page_words in read_pages(path):
        page_count = page_number
        words.extend(page_words)
    return words, page_count
