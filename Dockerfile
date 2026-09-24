# Ecrans Svelte (frontend/) compiles a part : node n'entre pas dans l'image
# finale, seul le bundle (frontend_dist/) y est copie.
FROM node:22-slim AS front
WORKDIR /build/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-fund --no-audit
COPY frontend/ ./
RUN npx vite build

FROM python:3.12-slim

RUN useradd -r -s /bin/false financy
WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY --chown=financy:financy . .
# Hors de static/ : en prod, static/ est monte depuis le depot par-dessus
# l'image, et masquerait le bundle.
COPY --from=front --chown=financy:financy /build/frontend_dist ./frontend_dist
USER financy

ENV FLASK_ENV=production
ENV PORT=5017
EXPOSE 5017

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:5017/login')" || exit 1

CMD ["gunicorn", "--bind", "0.0.0.0:5017", "--workers", "1", "--threads", "2", "--timeout", "120", "app:app"]
