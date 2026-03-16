FROM python:3.12-slim
WORKDIR /app
COPY api/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY ../shared/ /app/shared/
COPY ../strategies/ /app/strategies/
COPY ../params/ /app/params/
COPY ../openclaw_trader/ /app/openclaw_trader/
COPY api/ /app/dashboard/api/
ENV PYTHONPATH=/app
CMD ["uvicorn", "dashboard.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
