FROM python:3.12-slim

LABEL org.opencontainers.image.title="arr-mcp"
LABEL org.opencontainers.image.description="MCP server for home media stack management"
LABEL org.opencontainers.image.licenses="MIT"

WORKDIR /app

COPY pyproject.toml README.md ./
COPY src/ ./src/

RUN pip install --no-cache-dir .

EXPOSE 8081

ENV ARR_MCP_LOG_LEVEL=info

CMD ["arr-mcp"]
