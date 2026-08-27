FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir -e .
COPY configs ./configs
COPY outputs ./outputs
CMD ["roulette-opt", "--help"]
