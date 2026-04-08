FROM python:3.12-slim

RUN useradd -r -s /bin/false financy
WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY --chown=financy:financy . .
USER financy

ENV FLASK_ENV=production
ENV PORT=5017
EXPOSE 5017

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:5017/login')" || exit 1

CMD ["gunicorn", "--bind", "0.0.0.0:5017", "--workers", "2", "--timeout", "120", "app:app"]
