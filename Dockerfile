FROM ubuntu:24.04

# Python + Tesseract com idioma portugues (pacotes do Ubuntu)
RUN apt-get update \
    && apt-get install -y --no-install-recommends python3 python3-venv tesseract-ocr tesseract-ocr-por \
    && rm -rf /var/lib/apt/lists/* \
    && python3 -m venv /venv
ENV PATH=/venv/bin:$PATH

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY ocr_server.py .

RUN useradd --create-home ocr
USER ocr

# Tesseract com 1 thread por processo: nos testes foi mais rapido que o padrao (multithread)
ENV OMP_THREAD_LIMIT=1 \
    PYTHONUNBUFFERED=1

EXPOSE 5001
# timeout de 15 min por requisicao (extratos longos escaneados)
CMD ["sh", "-c", "exec gunicorn --workers ${GUNICORN_WORKERS:-2} --timeout 900 --bind 0.0.0.0:5001 --access-logfile - ocr_server:app"]
