FROM python:3.13-slim
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 OPENBLAS_NUM_THREADS=1
ENV JUDGMENT_DATA_DIR=/var/data/trading-journal
WORKDIR /app
COPY deploy/requirements-backend.txt /app/deploy/requirements-backend.txt
RUN pip install --no-cache-dir --only-binary=:all: --require-hashes -r /app/deploy/requirements-backend.txt
# app.js supplies only the existing public Firebase web configuration.
COPY app_server.py web_assets.py app.js /app/
COPY judgment/ /app/judgment/
COPY investment/src/investment_app/ /app/investment/src/investment_app/
COPY investment/config/ /app/investment/config/
CMD ["python", "app_server.py", "--host", "0.0.0.0", "--allow-origin", "https://piro-develop.github.io"]
