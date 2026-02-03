import os

# Telegram API credentials
# Get these from https://my.telegram.org
API_ID = os.getenv("TELEGRAM_API_ID", "")
API_HASH = os.getenv("TELEGRAM_API_HASH", "")

# Your phone number (with country code, e.g., +39123456789)
PHONE_NUMBER = os.getenv("PHONE_NUMBER", "")

# Target user to monitor (username without @ or user ID)
# You can get user ID by forwarding their message to @userinfobot
TARGET_USER = os.getenv("TARGET_USER", "")

# Your display name (as it appears in Telegram, for v3 dashboard color coding)
MY_NAME = os.getenv("MY_NAME", "")

# Persistent data directory (use /data on Render, local dir otherwise)
DATA_DIR = os.getenv("DATA_DIR", os.path.dirname(__file__))

# Session name (will create a .session file)
SESSION_NAME = os.path.join(DATA_DIR, "telegram_monitor")

# Database path
DATABASE_PATH = os.path.join(DATA_DIR, "messages.db")

# Media storage path
MEDIA_PATH = os.path.join(DATA_DIR, "media")

# Dashboard settings
DASHBOARD_PASSWORD = os.getenv("DASHBOARD_PASSWORD", "")
DASHBOARD_HOST = os.getenv("DASHBOARD_HOST", "0.0.0.0")
DASHBOARD_PORT = int(os.getenv("DASHBOARD_PORT", "5001"))
SECRET_KEY = os.getenv("SECRET_KEY", "change-this-secret-key-in-production")

# AI Assistant settings (Claude API)
# Get your API key from https://console.anthropic.com/
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")

# Local LLM settings (LM Studio or compatible OpenAI API server)
# Use localhost when running locally, Tailscale IP when remote
LOCAL_LLM_URL = os.getenv("LOCAL_LLM_URL", "http://localhost:1234/v1")
LOCAL_LLM_TAILSCALE_URL = os.getenv("LOCAL_LLM_TAILSCALE_URL", "")
LOCAL_LLM_MODEL = os.getenv("LOCAL_LLM_MODEL", "")

# Transcription settings (OpenAI Whisper API)
# Get your API key from https://platform.openai.com/
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
CLAUDE_CODE_OAUTH_TOKEN = os.getenv("CLAUDE_CODE_OAUTH_TOKEN", "")


# Web Push VAPID Keys (for iOS PWA push notifications)
# Generate new keys with: python3 -c "from cryptography.hazmat.primitives.asymmetric import ec; ..."
VAPID_PUBLIC_KEY = os.getenv("VAPID_PUBLIC_KEY", "")
VAPID_PRIVATE_KEY = os.getenv("VAPID_PRIVATE_KEY", "")
VAPID_CLAIMS_EMAIL = os.getenv("VAPID_CLAIMS_EMAIL", "mailto:your-email@example.com")

CONTROL_ROOM_BASE_URL = os.getenv("CONTROL_ROOM_BASE_URL", "")
CONTROL_ROOM_API_KEY = os.getenv("CONTROL_ROOM_API_KEY", "")
CONTROL_ROOM_WEBHOOK_SECRET = os.getenv("CONTROL_ROOM_WEBHOOK_SECRET", "")

# Render API (for programmatic deploys, env vars, etc.)
RENDER_API_KEY = os.getenv("RENDER_API_KEY", "")
RENDER_SERVICE_ID = os.getenv("RENDER_SERVICE_ID", "")
