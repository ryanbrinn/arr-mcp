FROM python:3.12-slim

LABEL org.opencontainers.image.title="arr-mcp"
LABEL org.opencontainers.image.description="MCP server for home media stack management"
LABEL org.opencontainers.image.licenses="MIT"

WORKDIR /app

# Install podman-compose for stack management
RUN apt-get update && apt-get install -y --no-install-recommends \
    podman-compose \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml ./
COPY src/ ./src/

RUN pip install --no-cache-dir -e .

EXPOSE 8081

ENV ARR_MCP_LOG_LEVEL=info

CMD ["arr-mcp"]
