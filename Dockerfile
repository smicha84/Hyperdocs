FROM python:3.11-slim

WORKDIR /app

# Install dependencies first (cached layer)
COPY pyproject.toml requirements.txt ./
RUN pip install --no-cache-dir .

# Copy application code
COPY . .
RUN pip install --no-cache-dir .

ENTRYPOINT ["hyperdocs"]
CMD ["--help"]
