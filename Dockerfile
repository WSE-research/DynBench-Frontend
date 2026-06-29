FROM python:3.14-slim-trixie

RUN apt update && apt install -y ca-certificates curl

# Copy requirement file first (to leverage Docker layer caching)
COPY requirements.txt .

RUN python -m pip install --upgrade pip 
RUN python -m pip install -r requirements.txt

COPY . /app
WORKDIR /app

RUN python -m pytest -v

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD curl -sf http://localhost:8501/health || exit 1

CMD ["python", "run.py"]
