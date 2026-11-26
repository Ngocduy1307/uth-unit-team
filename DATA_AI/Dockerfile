FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 TMPDIR=/tmp
RUN apt-get update && apt-get install -y --no-install-recommends tesseract-ocr tesseract-ocr-vie tesseract-ocr-eng fonts-dejavu-core libgl1 libglib2.0-0 && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
RUN groupadd --system --gid 10001 dataai && useradd --system --uid 10001 --gid 10001 --home-dir /home/dataai --create-home dataai \
    && mkdir -p /app/storage /app/exports /tmp \
    && chown -R 10001:10001 /app /home/dataai \
    && chmod 0700 /app/storage /app/exports
COPY --chown=10001:10001 . .
EXPOSE 8001
USER 10001:10001
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8001"]
