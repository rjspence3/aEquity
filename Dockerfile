FROM python:3.11-slim

WORKDIR /app

COPY pyproject.toml .
RUN pip install --no-cache-dir .

COPY . .

EXPOSE 8501

CMD streamlit run app.py \
    --server.port $PORT \
    --server.address 0.0.0.0 \
    --server.headless true
