FROM python:3.10-slim-trixie

RUN apt update && apt install -y ca-certificates curl

# Copy requirement file first (to leverage Docker layer caching)
COPY requirements.txt .

RUN python -m pip install --upgrade pip 
RUN python -m pip install -r requirements.txt

COPY . /app
WORKDIR /app

# ENTRYPOINT streamlit run server.py --server.address=0.0.0.0
CMD ["streamlit", "run", "server.py", "--server.address", "0.0.0.0"]
