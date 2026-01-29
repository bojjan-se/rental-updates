FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
RUN mkdir -p data logs

RUN useradd -m rental && chown -R rental:rental /app
USER rental

CMD ["python3", "run.py"]
