# syntax=docker/dockerfile:1
# Bagimliliklar ayri katmanda kurulur; son imajda derleyici/pip onbellegi yok.
FROM python:3.15-slim AS build
ENV PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /w
COPY requirements.txt .
RUN python -m venv /opt/venv && /opt/venv/bin/pip install --no-compile -r requirements.txt

FROM python:3.15-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PATH=/opt/venv/bin:$PATH
# Yetkisiz, kabuksuz, ev dizinsiz kullanici. /data: SQLite (adlandirilmis volume).
RUN useradd --system --uid 10001 --user-group --no-create-home --shell /usr/sbin/nologin panel \
 && mkdir /data && chown 10001:10001 /data && chmod 700 /data
COPY --from=build /opt/venv /opt/venv
COPY bytepanel /app/bytepanel
WORKDIR /app
USER 10001:10001
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=4s --start-period=15s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=3).status == 200 else 1)"
CMD ["uvicorn", "bytepanel.web:main", "--factory", "--host", "0.0.0.0", "--port", "8000", \
     "--no-server-header", "--timeout-keep-alive", "10", "--limit-concurrency", "50"]
