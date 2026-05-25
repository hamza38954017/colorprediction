"""
config.py — All runtime configuration read live from Firebase.
Set FIREBASE_URL and FIREBASE_SECRET in your environment variables.
"""
import os
import firebase_helper as fb

# ── Firebase ──────────────────────────────────────────────────────────────────
FIREBASE_URL    = os.environ.get("FIREBASE_URL", "")
FIREBASE_SECRET = os.environ.get("FIREBASE_SECRET", "")

# ── Flask (admin panel) ───────────────────────────────────────────────────────
SECRET_KEY = os.environ.get("SECRET_KEY", "colourbot-secret-2026")
FLASK_PORT  = int(os.environ.get("PORT", 5000))

# ── Live config helpers (always read fresh from Firebase) ─────────────────────
def get_config():
    return fb.get("config") or {}

def cfg(key, default=""):
    return get_config().get(key, default)

# ── Shortcuts ─────────────────────────────────────────────────────────────────
def BOT_TOKEN():         return os.environ.get("BOT_TOKEN", "").strip() or cfg("bot_token")
def BOT_USERNAME():      return cfg("bot_username", "YourBotUsername")
def SUPPORT_USERNAME():  return cfg("support_username", "@support")
def RULES_TEXT():        return cfg("rules_text", "📋 Rules coming soon.")
def ADMIN_USERNAME():
    v = cfg("admin_username", "").strip()
    return v if v else os.environ.get("ADMIN_USERNAME", "admin")
def ADMIN_PASSWORD():
    v = cfg("admin_password", "").strip()
    return v if v else os.environ.get("ADMIN_PASSWORD", "admin123")
def PANEL_NAME():        return cfg("panel_name", "ColourBot Admin")
def PANEL_COPYRIGHT():   return cfg("panel_copyright", "© 2026 ColourBot")
def MIN_DEPOSIT():       return int(cfg("min_deposit", 100))
def MIN_WITHDRAWAL():    return int(cfg("min_withdrawal", 100))
def MAX_WITHDRAWAL():    return int(cfg("max_withdrawal", 50000))
def REFER_COMMISSION():  return float(cfg("refer_commission", 5))
def SIGNUP_BONUS():      return int(cfg("signup_bonus", 50))
def NOTIFY_CHAT_IDS():
    raw = cfg("notify_chat_ids", "")
    return [x.strip() for x in raw.split(",") if x.strip()] if raw else []
