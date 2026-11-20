# NeuroBridge web app (Groq / Gemini / Tavily). The local Qwen models need a GPU and are not
# included here; run them from Colab (Demo/RUN_NeuroBridge_Website.ipynb).
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY agent ./agent
COPY nbapp ./nbapp
COPY scripts ./scripts
RUN sed -i "s/\r$//" scripts/*.sh
RUN useradd -m appuser && mkdir -p /tmp/neurobridge && chown -R appuser /app /tmp/neurobridge
USER appuser
ENV NEUROBRIDGE_APP_DB=/tmp/neurobridge/app.sqlite3 \
    NEUROBRIDGE_BOOKING_DB=/tmp/neurobridge/bookings.sqlite3 \
    NEUROBRIDGE_DISABLE_LEGACY_API=1 \
    NEUROBRIDGE_SEARCH_COUNTRY=india \
    PORT=10000
EXPOSE 10000
HEALTHCHECK CMD python -c "import urllib.request,os;urllib.request.urlopen('http://localhost:%s/health'%os.environ.get('PORT','10000'))"
CMD ["sh", "scripts/start_web.sh"]
