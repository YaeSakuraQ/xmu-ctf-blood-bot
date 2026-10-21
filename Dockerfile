FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    TZ=Asia/Shanghai

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates tzdata \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
# Retry the whole command too: a truncated index JSON response is not covered
# by pip's connection retries.
RUN set -eu; \
    attempt=1; \
    until python -m pip install --timeout 120 --retries 5 -r requirements.txt; do \
        if [ "$attempt" -ge 3 ]; then exit 1; fi; \
        echo "Dependency installation failed; retrying ($attempt/3)..." >&2; \
        attempt=$((attempt + 1)); \
        sleep 5; \
    done

COPY bot.py .
COPY ctfblood ./ctfblood
COPY plugins ./plugins

RUN mkdir -p /app/data

EXPOSE 8080
CMD ["python", "bot.py"]
