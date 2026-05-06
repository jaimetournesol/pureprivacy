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

# Pre-create the data dirs so the volume copy-on-mount lays them down
# inside the named volume on first boot.  We deliberately do NOT add a
# USER 10001 directive here: the container reads
# /shared/secrets/mcp_bearer_token (mode 0600, root-owned, written by
# the init container) and /shared/secrets/mcp_bot_credentials.json
# (same).  A non-root in-container user can't read those without us
# loosening permissions on the on-disk secrets — bad trade.  The
# compose file pins this container at cap_drop:ALL +
# no-new-privileges:true + read_only:true; root inside that sandbox has
# no usable privileges on the host, so it's the cleaner posture.
RUN mkdir -p /data /data/uploads /data/store

EXPOSE 8089
CMD ["python", "-m", "pureprivacy_mcp"]
