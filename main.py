"""
main.py — Entry point.
Runs the Telegram bot polling in a background thread
and the Flask admin panel on the main thread (for Render/Railway/Heroku).
"""
import threading
import bot
import app as admin_app
from config import FLASK_PORT

if __name__ == "__main__":
    # Start Telegram bot in background
    bot_thread = threading.Thread(target=bot.run_bot, daemon=True)
    bot_thread.start()
    print(f"🤖 Bot thread started")

    # Run Flask admin panel (blocking)
    print(f"🌐 Admin panel starting on port {FLASK_PORT}")
    admin_app.run_flask()
