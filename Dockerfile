FROM python:3.14-slim

ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PIP_NO_CACHE_DIR=1
WORKDIR /app
COPY requirements.txt .
# CPU-only torch: drop the CUDA wheels from the lock and pull torch from the CPU index.
RUN grep -vE '^(nvidia-|cuda-|triton|torch)' requirements.txt > /tmp/req.txt \
    && pip install -r /tmp/req.txt \
    && pip install torch==2.11.0 --index-url https://download.pytorch.org/whl/cpu

COPY . .
CMD ["uvicorn", "app.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
