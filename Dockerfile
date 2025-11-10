FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    GLIDER_CONFIG_DIR=/data/glider

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    ca-certificates \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
COPY aggregator/requirements.txt aggregator/requirements.txt

RUN pip install --no-cache-dir -r requirements.txt && \
    pip install --no-cache-dir -r aggregator/requirements.txt

COPY . .

RUN mkdir -p /data/glider && \
    chmod +x docker-entrypoint.sh glider/glider && \
    for file in aggregator/subconverter/subconverter-* aggregator/clash/clash-*; do \
        if [ -e "$file" ]; then chmod +x "$file"; fi; \
    done

EXPOSE 10707 10710

ENTRYPOINT ["./docker-entrypoint.sh"]
