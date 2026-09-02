FROM golang:1.25-bookworm AS alpaca-cli

RUN GOBIN=/out go install github.com/alpacahq/cli/cmd/alpaca@v0.0.14

FROM python:3.13-slim

WORKDIR /app
COPY pyproject.toml README.md LICENSE ./
COPY src ./src
RUN pip install --no-cache-dir .
COPY --from=alpaca-cli /out/alpaca /usr/local/bin/alpaca

ENV BROKER_MODE=demo EXECUTION_MODE=preview PYTHONUNBUFFERED=1
EXPOSE 8787
CMD ["glassbox-alpha", "serve", "--host", "0.0.0.0", "--watch-interval", "300"]
