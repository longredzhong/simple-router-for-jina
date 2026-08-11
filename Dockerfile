FROM python:3.11-slim

RUN pip install --no-cache-dir "click>=8.4.2,<9" "requests>=2.34.2,<3"

WORKDIR /app
COPY simple-router.py /app/simple-router.py

EXPOSE 8080

ENTRYPOINT ["python", "/app/simple-router.py", "serve", "--config", "/app/config.toml"]
