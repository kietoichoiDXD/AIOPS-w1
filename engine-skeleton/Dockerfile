# ===========================================================================
# FinOps Watch AI Engine — Production Dockerfile
# Deployment Contract: ECS Fargate / 1 vCPU / 2048 MB / Port 8080
# ===========================================================================

FROM python:3.12-slim AS base

# Security: non-root user
RUN groupadd -r appuser && useradd -r -g appuser appuser

WORKDIR /app

# Layer caching: install deps before copying source
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Ownership
RUN chown -R appuser:appuser /app

USER appuser

# Health check for ALB (Deployment Contract §Health check)
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8080/health')" || exit 1

EXPOSE 8080

# Production server: uvicorn with workers sized for 1 vCPU
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080", "--workers", "2", "--log-level", "info"]
