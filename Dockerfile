FROM python:3.11-slim

# System-Abhängigkeiten
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# Arbeitsverzeichnis
WORKDIR /app

# Dependencies installieren
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# App kopieren
COPY *.py .
COPY config.yaml.example .

# Bot starten
CMD ["python", "bot.py"]
