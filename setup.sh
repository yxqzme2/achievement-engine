#!/usr/bin/env bash
set -e

# Achievement Engine - Interactive Setup
# Run this after cloning the repo: ./setup.sh

echo ""
echo "=== Achievement Engine Setup ==="
echo ""

# --- Check prerequisites ---
missing=""
if ! command -v docker &>/dev/null; then
  missing="docker"
fi
if ! docker compose version &>/dev/null 2>&1; then
  if [ -n "$missing" ]; then
    missing="$missing, docker compose"
  else
    missing="docker compose"
  fi
fi

if [ -n "$missing" ]; then
  echo "ERROR: Missing required tools: $missing"
  echo "Install Docker: https://docs.docker.com/get-docker/"
  exit 1
fi

echo "Docker found: $(docker --version)"
echo ""

# --- Create .env if it doesn't exist ---
if [ -f .env ]; then
  echo ".env already exists, skipping creation."
  echo "  (Delete .env and re-run this script to start fresh)"
  echo ""
else
  cp .env.example .env
  echo "Created .env from .env.example"
  echo ""
fi

# --- Prompt for required settings ---
echo "--- Audiobookshelf Connection ---"
echo ""
read -rp "Audiobookshelf server URL (e.g. http://192.168.1.50:13378): " abs_url
abs_url="${abs_url:-http://audiobookshelf:80}"

echo ""
echo "You need an API token for each user you want to track."
echo "Get tokens from: Audiobookshelf > Settings > Users > [user] > API Token"
echo ""
echo "For a SINGLE user, just paste one token."
echo "For MULTIPLE users, enter them as: username1:token1,username2:token2"
echo ""
read -rp "API token(s): " abs_tokens

# Determine if single or multi-user
if [[ "$abs_tokens" == *":"* ]]; then
  # Multi-user format
  abs_token=""
  abs_tokens_val="$abs_tokens"
  echo "  -> Multi-user mode detected"
else
  # Single token
  abs_token="$abs_tokens"
  abs_tokens_val=""
  echo "  -> Single-user mode detected"
fi

echo ""
echo "--- Optional: Discord Notifications ---"
echo "(Press Enter to skip)"
read -rp "Discord webhook URL: " discord_webhook
echo ""

echo "--- Optional: User Display Names ---"
echo "Map usernames to friendly names for the dashboard."
echo "Format: absuser1:Display Name,absuser2:Display Name"
echo "(Press Enter to skip)"
read -rp "User aliases: " user_aliases
echo ""

echo "--- Optional: Email Notifications ---"
echo "Send email alerts when achievements are earned."
echo "(Press Enter to skip all email settings)"
read -rp "SMTP server hostname (e.g. smtp.gmail.com): " smtp_host

if [ -n "$smtp_host" ]; then
  read -rp "SMTP port [587]: " smtp_port
  smtp_port="${smtp_port:-587}"
  read -rp "SMTP username: " smtp_username
  read -rp "SMTP password: " smtp_password
  read -rp "From email address: " smtp_from
  echo ""
  echo "Map usernames to email addresses for notifications."
  echo "Format: absuser1:user1@email.com,absuser2:user2@email.com"
  read -rp "User emails: " user_emails
  echo ""
  echo "  -> Email notifications enabled"
else
  echo "  -> Email notifications skipped"
fi
echo ""

# --- Write docker-compose.override.yml with actual values ---
# (keeps docker-compose.yml clean for git)
cat > docker-compose.override.yml <<EOF
services:
  abs-stats:
    environment:
      - ABS_URL=${abs_url}
EOF

if [ -n "$abs_token" ]; then
  cat >> docker-compose.override.yml <<EOF
      - ABS_TOKEN=${abs_token}
EOF
fi

if [ -n "$abs_tokens_val" ]; then
  cat >> docker-compose.override.yml <<EOF
      - ABS_TOKENS=${abs_tokens_val}
EOF
fi

cat >> docker-compose.override.yml <<EOF
      - ENGINE_URL=http://achievement-engine:8000
EOF

if [ -n "$discord_webhook" ]; then
  cat >> docker-compose.override.yml <<EOF
      - DISCORD_WEBHOOK_URL=${discord_webhook}
EOF
fi

echo "Created docker-compose.override.yml with your settings."

# --- Update .env with achievement engine settings ---
sed -i "s|^ABSSTATS_BASE_URL=.*|ABSSTATS_BASE_URL=http://abs-stats:3000|" .env

if [ -n "$user_aliases" ]; then
  sed -i "s|^USER_ALIASES=.*|USER_ALIASES=${user_aliases}|" .env
fi

if [ -n "$discord_webhook" ]; then
  sed -i "s|^DISCORD_PROXY_URL=.*|DISCORD_PROXY_URL=http://abs-stats:3000/api/discord-notify|" .env
fi

if [ -n "$smtp_host" ]; then
  sed -i "s|^SMTP_HOST=.*|SMTP_HOST=${smtp_host}|" .env
  sed -i "s|^SMTP_PORT=.*|SMTP_PORT=${smtp_port}|" .env
  sed -i "s|^SMTP_USERNAME=.*|SMTP_USERNAME=${smtp_username}|" .env
  sed -i "s|^SMTP_PASSWORD=.*|SMTP_PASSWORD=${smtp_password}|" .env
  sed -i "s|^SMTP_FROM=.*|SMTP_FROM=${smtp_from}|" .env
  if [ -n "$user_emails" ]; then
    sed -i "s|^USER_EMAILS=.*|USER_EMAILS=${user_emails}|" .env
  fi
fi

echo "Updated .env with your settings."
echo ""

# --- Create data directory ---
mkdir -p data icons

# --- Copy achievements.points.json to data/ if not already there ---
if [ ! -f data/achievements.points.json ] && [ -f achievements.points.json ]; then
  cp achievements.points.json data/achievements.points.json
  echo "Copied achievements.points.json to data/"
fi

echo ""
echo "=== Setup Complete ==="
echo ""
echo "Review your settings:"
echo "  - docker-compose.override.yml  (abs-stats connection)"
echo "  - .env                          (achievement engine config)"
echo ""
echo "Start the services:"
echo "  docker compose up -d"
echo ""
echo "Then open: http://localhost:8000"
echo ""
