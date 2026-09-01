FROM python:3.13-slim

WORKDIR /app
COPY pyproject.toml README.md LICENSE ./
COPY src ./src
RUN pip install --no-cache-dir .

ENV BROKER_MODE=demo EXECUTION_MODE=preview PYTHONUNBUFFERED=1
EXPOSE 8787
CMD ["glassbox-alpha", "serve", "--host", "0.0.0.0", "--port", "8787"]

