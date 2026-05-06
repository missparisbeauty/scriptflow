# ScriptFlow Cloud Run image
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PORT=8080

# 非 root 執行（vibecoding-safety 要求）
RUN useradd --create-home --uid 1000 app

WORKDIR /app

# 先裝依賴利用 layer cache
COPY --chown=app:app requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# 應用程式碼
COPY --chown=app:app . .

USER app

EXPOSE 8080

# Cloud Run 會以 $PORT 環境變數注入埠號
CMD exec uvicorn main:app --host 0.0.0.0 --port ${PORT}
