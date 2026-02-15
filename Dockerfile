FROM python:3.12-slim

# tzdata for America/New_York logic (behavior_time)
RUN apt-get update \
  && apt-get install -y --no-install-recommends tzdata ca-certificates \
  && rm -rf /var/lib/apt/lists/*

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# If you already have requirements.txt, use it.
# Otherwise, create requirements.txt with what your project uses.
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

# Copy your app code
COPY app /app/app

# Copy HTML dashboard files
COPY dashboard.html /app/static/dashboard.html
COPY leaderboard.html /app/static/leaderboard.html
COPY timeline.html /app/static/timeline.html

# Default runtime envs (override in Unraid)
ENV POLL_SECONDS=300 \
    ACHIEVEMENTS_PATH=/data/achievements.points.json \
    TZ=America/New_York

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]

