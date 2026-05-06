FROM python:3.12-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        curl \
        libolm3 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY src/ /app/src/

ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONPATH=/app/src

# Non-root account for the MCP process. /data is a named docker volume:
# we pre-create the mountpoint with the right ownership so the first-time
# volume copy preserves it.  Defense in depth on top of read_only +
# cap_drop in compose.
RUN useradd --uid 10001 --no-create-home --shell /usr/sbin/nologin mcp \
    && mkdir -p /data /data/uploads /data/store \
    && chown -R 10001:10001 /data
USER 10001:10001

EXPOSE 8089
CMD ["python", "-m", "pureprivacy_mcp"]
