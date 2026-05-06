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

EXPOSE 8089
CMD ["python", "-m", "pureprivacy_mcp"]
