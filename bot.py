"""
ColourPredict Telegram Bot — bot.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Features:
  • 24/7 automated colour prediction game (Green / Violet / Red)
  • Persistent wallet using Firebase Realtime Database
  • Manual deposit: coin packages → QR/UPI from DB → UTR verification
  • Transaction history
  • Refer & Earn with commission
  • Rules, Customer Support
  • Animated win/loss GIF via ffmpeg (optional)
"""

import telebot
from telebot import types
import datetime, random, string, time, re, threading, os, io, subprocess
import requests
import firebase_helper as fb
from config import (
    BOT_TOKEN, BOT_USERNAME, SUPPORT_USERNAME, RULES_TEXT,
    MIN_DEPOSIT, MIN_WITHDRAWAL, MAX_WITHDRAWAL,
    REFER_COMMISSION, NOTIFY_CHAT_IDS, SIGNUP_BONUS,
)

# ── Boot ──────────────────────────────────────────────────────────────────────
def _get_token():
    token = os.environ.get("BOT_TOKEN", "").strip()
    if token:
        return token
    token = BOT_TOKEN()
    if token:
        return token
    print("⚠️  BOT_TOKEN not found in env or Firebase /config/bot_token")
    return None

_BOT_TOKEN = _get_token()
bot = telebot.TeleBot(_BOT_TOKEN, parse_mode=None) if _BOT_TOKEN else None

# ── Game globals ──────────────────────────────────────────────────────────────
active_users     = set()      # chat_ids in the game loop
active_messages  = {}         # chat_id → message_id of live countdown msg
last_outcomes    = []         # last 5 results
current_order_id = None       # current round id
current_bets     = {}         # user_id → {color, amount, chat_id}
active_menus     = {}         # user_id → bet-amount menu message_id
bet_lock         = threading.Lock()

COLOR_EMOJIS = {"Green": "🟢", "Violet": "🟣", "Red": "🔴"}
MULTIPLIERS  = {"Green": 1.9,  "Violet": 4.9,  "Red": 1.9}

# ── State (in-memory, persisted to Firebase for survival across restarts) ─────
user_states = {}
user_temp   = {}

def get_state(cid):    return user_states.get(str(cid))
def set_state(cid, s): user_states[str(cid)] = s
def clear_state(cid):
    user_states.pop(str(cid), None)
    user_temp.pop(str(cid), None)
    try: fb.delete(f"user_temp/{cid}")
    except: pass

def get_temp(cid):
    cid = str(cid)
    if cid not in user_temp:
        saved = fb.get(f"user_temp/{cid}")
        if saved and isinstance(saved, dict):
            user_temp[cid] = saved
    return user_temp.get(cid, {})

def set_temp(cid, d):
    cid = str(cid)
    user_temp[cid] = d
    try: fb.put(f"user_temp/{cid}", d)
    except: pass

def upd_temp(cid, d):
    cid = str(cid)
    user_temp.setdefault(cid, {}).update(d)
    try: fb.patch(f"user_temp/{cid}", d)
    except: pass

# ── Helpers ───────────────────────────────────────────────────────────────────
def now_str():  return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
def now_dt():   return datetime.datetime.now()
def gen_code(n=8): return "".join(random.choices(string.ascii_uppercase + string.digits, k=n))
def gen_order_id(): return "ORD" + "".join(random.choices(string.digits, k=8))
def fmt_coins(n):
    try: return f"{int(n):,} 🪙"
    except: return f"{n} 🪙"

def send_notify(text):
    for cid in NOTIFY_CHAT_IDS():
        try: bot.send_message(cid, text, parse_mode="Markdown")
        except: pass

def send_msg(cid, text, **kw):
    try: bot.send_message(cid, text, parse_mode="Markdown", **kw)
    except Exception as e: print(f"[MSG] {cid}: {e}")

# ── User helpers ──────────────────────────────────────────────────────────────
def get_user(cid):
    return fb.get(f"users/{cid}")

def ensure_user(message, referred_by=None):
    cid = str(message.chat.id)
    u = fb.get(f"users/{cid}")
    if u:
        fb.patch(f"users/{cid}", {"last_seen": now_str()})
        return u, False
    # New user
    rc = gen_code()
    while fb.get(f"refer_codes/{rc}"):
        rc = gen_code()
    fn = (message.from_user.first_name or "").strip()
    ln = (message.from_user.last_name  or "").strip()
    bonus = SIGNUP_BONUS()
    data = {
        "chat_id": cid,
        "full_name": f"{fn} {ln}".strip(),
        "first_name": fn, "last_name": ln,
        "username": message.from_user.username or "",
        "refer_code": rc, "referred_by": referred_by or "",
        "wallet": bonus,
        "total_earned": 0, "total_deposited": 0,
        "total_wagered": 0, "total_won": 0,
        "verified_refer": 0, "pending_refer": 0, "refer_count": 0,
        "games_played": 0, "games_won": 0,
        "created_at": now_str(), "last_seen": now_str(),
    }
    fb.put(f"users/{cid}", data)
    fb.put(f"refer_codes/{rc}", cid)
    # Log signup bonus transaction
    if bonus > 0:
        fb.put(f"users/{cid}/transactions/SIGNUP", {
            "type": "bonus", "for": "Signup Bonus",
            "amount": bonus, "status": "success", "date": now_str()
        })
    # Handle referral
    if referred_by and referred_by != cid:
        ref = fb.get(f"users/{referred_by}")
        if ref:
            fb.patch(f"users/{referred_by}", {
                "pending_refer": ref.get("pending_refer", 0) + 1,
                "refer_count":   ref.get("refer_count", 0) + 1,
            })
            fb.put(f"referrals/{referred_by}/{cid}", {
                "chat_id": cid, "name": data["full_name"],
                "status": "pending", "joined_at": now_str(), "earned": 0
            })
            send_msg(referred_by,
                f"🎉 *New Referral!*\n"
                f"━━━━━━━━━━━━━━━━━━━━━\n"
                f"👤 *{data['full_name']}* just joined using your link!\n"
                f"💸 You'll earn commission on their deposits.\n"
                f"Keep sharing your referral link!")
    return data, True

# ── Keyboards ─────────────────────────────────────────────────────────────────
def kb_main():
    m = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    m.add("🏠 Home",         "💰 Wallet")
    m.add("💳 Transactions",  "👥 Refer & Earn")
    m.add("👤 My Refer",     "📋 Rules")
    m.add("📞 Customer Support")
    return m

def kb_cancel():
    m = types.ReplyKeyboardMarkup(resize_keyboard=True)
    m.add("❌ Cancel")
    return m

def _guard(msg):
    cid = str(msg.chat.id)
    if not fb.get(f"users/{cid}"):
        cmd_start(msg)
        return False
    fb.patch(f"users/{cid}", {"last_seen": now_str()})
    return True

def _guard_cancel(msg):
    return msg.text and msg.text.strip() == "❌ Cancel"

# ═══════════════════════════════════════════════════════════════════════════════
# /start
# ═══════════════════════════════════════════════════════════════════════════════
@bot.message_handler(commands=["start", "play"])
def cmd_start(msg):
    cid = str(msg.chat.id)
    args = msg.text.split()
    ref_by = None
    if len(args) > 1:
        ref = fb.get(f"refer_codes/{args[1]}")
        if ref and str(ref) != cid:
            ref_by = str(ref)

    u, is_new = ensure_user(msg, ref_by)
    bonus = SIGNUP_BONUS()

    if is_new:
        greet = (
            f"🎉 *Welcome to ColourPredict!*\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n"
            f"👋 Hello *{u.get('first_name', 'Friend')}*!\n\n"
            f"🎁 You received *{fmt_coins(bonus)}* as signup bonus!\n"
            f"🎮 Predict colours, win multiplied coins!\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n"
            f"🟢 Green / 🔴 Red → *1.9×*\n"
            f"🟣 Violet → *4.9×*\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n"
            f"💰 Wallet: *{fmt_coins(u.get('wallet', 0))}*\n"
            f"👇 Use the menu below to get started!"
        )
    else:
        greet = (
            f"🏠 *Welcome Back!*\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n"
            f"👋 Hey *{u.get('first_name', 'Friend')}*!\n"
            f"💰 Wallet: *{fmt_coins(u.get('wallet', 0))}*\n"
            f"🎮 Games Played: *{u.get('games_played', 0)}*\n"
            f"🏆 Games Won: *{u.get('games_won', 0)}*"
        )

    send_msg(cid, greet, reply_markup=kb_main())

    # Add to game loop
    if msg.chat.id not in active_users:
        active_users.add(msg.chat.id)

# ═══════════════════════════════════════════════════════════════════════════════
# HOME
# ═══════════════════════════════════════════════════════════════════════════════
@bot.message_handler(func=lambda m: m.text == "🏠 Home")
def msg_home(msg):
    if not _guard(msg): return
    cid = str(msg.chat.id)
    u = get_user(cid)
    send_msg(cid,
        f"🏠 *Home*\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"👤 *{u.get('full_name', 'Friend')}*\n"
        f"💰 Wallet: *{fmt_coins(u.get('wallet', 0))}*\n"
        f"🎮 Games Played: *{u.get('games_played', 0)}*\n"
        f"🏆 Games Won: *{u.get('games_won', 0)}*\n"
        f"🤝 Referrals: *{u.get('refer_count', 0)}*\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"The live game runs 24/7 above ☝️",
        reply_markup=kb_main())

# ═══════════════════════════════════════════════════════════════════════════════
# WALLET
# ═══════════════════════════════════════════════════════════════════════════════
@bot.message_handler(func=lambda m: m.text == "💰 Wallet")
def msg_wallet(msg):
    if not _guard(msg): return
    _show_wallet(str(msg.chat.id))

def _show_wallet(cid):
    u = get_user(cid)
    if not u: return
    mk = types.InlineKeyboardMarkup(row_width=2)
    mk.add(
        types.InlineKeyboardButton("➕ Deposit Coins", callback_data="deposit_start"),
        types.InlineKeyboardButton("💸 Withdraw",     callback_data="withdraw_start"),
    )
    send_msg(cid,
        f"💰 *My Wallet*\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"🪙 Balance:        *{fmt_coins(u.get('wallet', 0))}*\n"
        f"📥 Total Deposited: *{fmt_coins(u.get('total_deposited', 0))}*\n"
        f"🎯 Total Wagered:   *{fmt_coins(u.get('total_wagered', 0))}*\n"
        f"🏆 Total Won:       *{fmt_coins(u.get('total_won', 0))}*\n"
        f"💸 Total Earned:    *{fmt_coins(u.get('total_earned', 0))}*\n"
        f"━━━━━━━━━━━━━━━━━━━━━",
        reply_markup=mk)

# ─── Deposit ──────────────────────────────────────────────────────────────────
@bot.callback_query_handler(func=lambda c: c.data == "deposit_start")
def cb_deposit_start(c):
    bot.answer_callback_query(c.id)
    cid = str(c.message.chat.id)
    _show_deposit_packages(cid)

@bot.message_handler(func=lambda m: m.text == "➕ Deposit")
def msg_deposit(msg):
    if not _guard(msg): return
    _show_deposit_packages(str(msg.chat.id))

def _show_deposit_packages(cid):
    """Show available coin packages fetched from Firebase."""
    packages = fb.get("deposit_packages") or {}
    if not packages:
        # Default packages if admin hasn't set any
        packages = {
            "pkg1": {"coins": 100,  "price": 100,  "bonus": 0,   "label": "Starter"},
            "pkg2": {"coins": 550,  "price": 500,  "bonus": 50,  "label": "Popular"},
            "pkg3": {"coins": 1200, "price": 1000, "bonus": 200, "label": "Value"},
            "pkg4": {"coins": 2700, "price": 2000, "bonus": 700, "label": "Premium"},
            "pkg5": {"coins": 7000, "price": 5000, "bonus": 2000,"label": "VIP"},
        }

    mk = types.InlineKeyboardMarkup(row_width=1)
    lines = ["💎 *Deposit Coins*\n━━━━━━━━━━━━━━━━━━━━━\n📦 *Choose a package:*\n"]
    for pkg_id, pkg in sorted(packages.items()):
        coins  = int(pkg.get("coins", 0))
        price  = int(pkg.get("price", 0))
        bonus  = int(pkg.get("bonus", 0))
        label  = pkg.get("label", "")
        total  = coins + bonus
        bonus_txt = f" + *{fmt_coins(bonus)} BONUS*" if bonus > 0 else ""
        lines.append(f"🔹 *{label}* — ₹{price:,} → {fmt_coins(coins)}{bonus_txt}")
        mk.add(types.InlineKeyboardButton(
            f"{'⭐' if bonus > 0 else '🔹'} {label} — ₹{price:,} → {total:,} 🪙",
            callback_data=f"depkg_{pkg_id}_{price}_{total}"
        ))
    mk.add(types.InlineKeyboardButton("❌ Cancel", callback_data="dep_cancel"))
    send_msg(cid, "\n".join(lines), reply_markup=mk)

@bot.callback_query_handler(func=lambda c: c.data.startswith("depkg_"))
def cb_deposit_package(c):
    bot.answer_callback_query(c.id)
    cid = str(c.message.chat.id)
    # Parse: depkg_{pkg_id}_{price}_{coins}
    parts = c.data.split("_")
    pkg_id = parts[1]
    price  = int(parts[2])
    coins  = int(parts[3])

    # Fetch payment info from Firebase
    pay_info = fb.get("payment_info") or {}
    upi_id   = pay_info.get("upi_id", "Not configured — contact support")
    pay_name = pay_info.get("name", "ColourBot")
    qr_url   = pay_info.get("qr_url", "")

    # Save temp state
    set_temp(cid, {
        "deposit_pkg": pkg_id,
        "deposit_price": price,
        "deposit_coins": coins,
    })
    set_state(cid, "wait_utr")

    text = (
        f"💳 *Payment Details*\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"📦 Package: *{fmt_coins(coins)}*\n"
        f"💵 Amount to Pay: *₹{price:,}*\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"🏦 *Pay to:*\n"
        f"   👤 Name: *{pay_name}*\n"
        f"   📱 UPI ID: `{upi_id}`\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"✅ After payment, enter your *12-digit UTR / Reference Number* below.\n\n"
        f"⚠️ Do NOT close this chat until you submit the UTR."
    )

    if qr_url:
        try:
            bot.send_photo(c.message.chat.id, qr_url, caption=text,
                           parse_mode="Markdown", reply_markup=kb_cancel())
            return
        except Exception as e:
            print(f"[QR Photo] {e}")

    send_msg(cid, text, reply_markup=kb_cancel())

@bot.message_handler(func=lambda m: get_state(str(m.chat.id)) == "wait_utr")
def handle_utr(msg):
    cid = str(msg.chat.id)
    if _guard_cancel(msg):
        clear_state(cid)
        send_msg(cid, "❌ *Deposit cancelled.*", reply_markup=kb_main())
        return

    utr = (msg.text or "").strip()
    # Validate: 12 digits
    if not re.match(r"^\d{12}$", utr):
        send_msg(cid,
            "❌ *Invalid UTR number.*\n"
            "Please enter your exact *12-digit* UTR / Reference Number:\n\n"
            "_(It should be numbers only, exactly 12 digits)_",
            reply_markup=types.ForceReply(selective=True))
        return

    temp = get_temp(cid)
    price  = temp.get("deposit_price", 0)
    coins  = temp.get("deposit_coins", 0)
    pkg_id = temp.get("deposit_pkg", "")
    dep_id = gen_order_id()

    u = get_user(cid)

    # Save deposit request to Firebase
    fb.put(f"deposit_requests/{dep_id}", {
        "dep_id":   dep_id,
        "chat_id":  cid,
        "user_name": u.get("full_name", ""),
        "username":  u.get("username", ""),
        "pkg_id":   pkg_id,
        "price":    price,
        "coins":    coins,
        "utr":      utr,
        "status":   "pending",
        "created_at": now_str(),
    })
    # Log transaction
    fb.put(f"users/{cid}/transactions/{dep_id}", {
        "type": "deposit", "for": f"Deposit ₹{price}",
        "amount": coins, "status": "pending", "date": now_str()
    })

    clear_state(cid)
    send_msg(cid,
        f"✅ *Deposit Request Submitted!*\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"📦 Coins: *{fmt_coins(coins)}*\n"
        f"💵 Amount: *₹{price:,}*\n"
        f"🔖 Reference: `{dep_id}`\n"
        f"🔐 UTR: `{utr}`\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"⏳ *Verification may take up to 1 hour.*\n"
        f"Coins will be automatically credited to your wallet.\n\n"
        f"📞 Contact support if not credited after 1 hour.",
        reply_markup=kb_main())

    send_notify(
        f"💰 *New Deposit Request!*\n"
        f"👤 {u.get('full_name', cid)} (@{u.get('username', 'N/A')})\n"
        f"📦 {fmt_coins(coins)} | ₹{price:,}\n"
        f"🔐 UTR: `{utr}`\n"
        f"🔖 Ref: `{dep_id}`"
    )

@bot.callback_query_handler(func=lambda c: c.data == "dep_cancel")
def cb_dep_cancel(c):
    bot.answer_callback_query(c.id, "Cancelled")
    cid = str(c.message.chat.id)
    clear_state(cid)
    try: bot.delete_message(cid, c.message.message_id)
    except: pass

# ─── Withdraw ─────────────────────────────────────────────────────────────────
@bot.callback_query_handler(func=lambda c: c.data == "withdraw_start")
def cb_withdraw_start(c):
    bot.answer_callback_query(c.id)
    cid = str(c.message.chat.id)
    u = get_user(cid)
    wallet = u.get("wallet", 0)
    min_w  = MIN_WITHDRAWAL()
    max_w  = MAX_WITHDRAWAL()
    if wallet < min_w:
        bot.answer_callback_query(c.id,
            f"❌ Minimum withdrawal is {fmt_coins(min_w)}. "
            f"Your balance: {fmt_coins(wallet)}",
            show_alert=True)
        return
    set_state(cid, "wait_withdraw_amount")
    send_msg(cid,
        f"🏦 *Withdraw Coins*\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"💰 Available: *{fmt_coins(wallet)}*\n"
        f"📉 Minimum: *{fmt_coins(min_w)}*\n"
        f"📈 Maximum: *{fmt_coins(max_w)}*\n\n"
        f"Enter the number of coins to withdraw:",
        reply_markup=kb_cancel())

@bot.message_handler(func=lambda m: get_state(str(m.chat.id)) == "wait_withdraw_amount")
def handle_withdraw_amount(msg):
    cid = str(msg.chat.id)
    if _guard_cancel(msg):
        clear_state(cid)
        send_msg(cid, "❌ *Cancelled.*", reply_markup=kb_main())
        return
    if not msg.text or not msg.text.strip().isdigit():
        send_msg(cid, "❌ Enter a valid number of coins:",
                 reply_markup=types.ForceReply(selective=True))
        return
    amount = int(msg.text.strip())
    u = get_user(cid)
    wallet = u.get("wallet", 0)
    min_w, max_w = MIN_WITHDRAWAL(), MAX_WITHDRAWAL()
    if amount < min_w:
        send_msg(cid, f"❌ Minimum is *{fmt_coins(min_w)}*. Enter again:",
                 reply_markup=types.ForceReply(selective=True)); return
    if amount > max_w:
        send_msg(cid, f"❌ Maximum is *{fmt_coins(max_w)}*. Enter again:",
                 reply_markup=types.ForceReply(selective=True)); return
    if amount > wallet:
        send_msg(cid, f"❌ Insufficient balance. Wallet: *{fmt_coins(wallet)}*. Enter less:",
                 reply_markup=types.ForceReply(selective=True)); return
    upd_temp(cid, {"withdraw_amount": amount})
    set_state(cid, "wait_withdraw_upi")
    send_msg(cid, "🏦 Enter your *UPI ID* (e.g. name@upi):",
             reply_markup=types.ForceReply(selective=True))

@bot.message_handler(func=lambda m: get_state(str(m.chat.id)) == "wait_withdraw_upi")
def handle_withdraw_upi(msg):
    cid = str(msg.chat.id)
    if _guard_cancel(msg):
        clear_state(cid)
        send_msg(cid, "❌ *Cancelled.*", reply_markup=kb_main())
        return
    upi = (msg.text or "").strip()
    if not upi:
        send_msg(cid, "❌ Enter a valid UPI ID:",
                 reply_markup=types.ForceReply(selective=True)); return
    temp   = get_temp(cid)
    amount = temp.get("withdraw_amount", 0)
    u      = get_user(cid)
    wd_id  = gen_order_id()

    # Deduct wallet immediately (held pending)
    fb.patch(f"users/{cid}", {"wallet": max(0, u.get("wallet", 0) - amount)})
    fb.put(f"withdrawals/{wd_id}", {
        "wd_id": wd_id, "chat_id": cid,
        "user_name": u.get("full_name", ""),
        "username": u.get("username", ""),
        "amount": amount, "upi": upi,
        "status": "pending", "created_at": now_str()
    })
    fb.put(f"users/{cid}/transactions/{wd_id}", {
        "type": "withdrawal", "for": upi,
        "amount": -amount, "status": "pending", "date": now_str()
    })
    clear_state(cid)
    send_msg(cid,
        f"✅ *Withdrawal Requested!*\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"🪙 Amount: *{fmt_coins(amount)}*\n"
        f"🏦 UPI: `{upi}`\n"
        f"🔖 ID: `{wd_id}`\n"
        f"⏳ Processing: 24–48 hours\n"
        f"━━━━━━━━━━━━━━━━━━━━━",
        reply_markup=kb_main())
    send_notify(
        f"🏦 *Withdrawal Request!*\n"
        f"👤 {u.get('full_name', cid)}\n"
        f"🪙 {fmt_coins(amount)} | UPI: `{upi}`\n"
        f"🔖 `{wd_id}`"
    )

# ═══════════════════════════════════════════════════════════════════════════════
# TRANSACTIONS
# ═══════════════════════════════════════════════════════════════════════════════
@bot.message_handler(func=lambda m: m.text == "💳 Transactions")
def msg_transactions(msg):
    if not _guard(msg): return
    cid = str(msg.chat.id)
    txns = fb.get(f"users/{cid}/transactions") or {}
    if not txns:
        send_msg(cid,
            "💳 *Transaction History*\n"
            "━━━━━━━━━━━━━━━━━━━━━\n"
            "No transactions yet.\n\n"
            "Play the game or deposit coins to get started!"); return

    ICONS   = {"deposit": "📥", "withdrawal": "📤", "bet": "🎮",
                "win": "🏆", "referral": "🤝", "bonus": "🎁"}
    ST_ICON = {"success": "✅", "pending": "⏳", "failed": "❌"}

    lines = ["💳 *Transaction History* (last 15)\n━━━━━━━━━━━━━━━━━━━━━"]
    sorted_txns = sorted(txns.items(), key=lambda x: x[1].get("date", ""), reverse=True)[:15]
    for tid, td in sorted_txns:
        icon = ICONS.get(td.get("type", ""), "📋")
        st   = ST_ICON.get(td.get("status", "pending"), "⏳")
        amt  = td.get("amount", 0)
        sign = "+" if amt > 0 else ""
        lines.append(
            f"{st} {icon} *{td.get('type', '').title()}*\n"
            f"   For: _{td.get('for', '')}_\n"
            f"   Amount: *{sign}{fmt_coins(amt)}* | {td.get('date', '')[:16]}"
        )
    send_msg(cid, "\n\n".join(lines))

# ═══════════════════════════════════════════════════════════════════════════════
# REFER & EARN
# ═══════════════════════════════════════════════════════════════════════════════
@bot.message_handler(func=lambda m: m.text == "👥 Refer & Earn")
def msg_refer_earn(msg):
    if not _guard(msg): return
    cid = str(msg.chat.id)
    u   = get_user(cid)
    rc  = u.get("refer_code", "")
    uname = BOT_USERNAME()
    link  = f"https://t.me/{uname}?start={rc}"
    comm  = REFER_COMMISSION()
    send_msg(cid,
        f"👥 *Refer & Earn*\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"💸 Earn *{comm}% commission* on every deposit your referrals make!\n\n"
        f"🔗 *Your Referral Link:*\n`{link}`\n\n"
        f"📊 *Your Stats:*\n"
        f"  👥 Total Referrals: *{u.get('refer_count', 0)}*\n"
        f"  ✅ Verified: *{u.get('verified_refer', 0)}*\n"
        f"  ⏳ Pending: *{u.get('pending_refer', 0)}*\n"
        f"  💰 Total Earned: *{fmt_coins(u.get('total_earned', 0))}*\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"📤 Share your link and start earning!")

# ═══════════════════════════════════════════════════════════════════════════════
# MY REFER
# ═══════════════════════════════════════════════════════════════════════════════
@bot.message_handler(func=lambda m: m.text == "👤 My Refer")
def msg_my_refer(msg):
    if not _guard(msg): return
    cid  = str(msg.chat.id)
    refs = fb.get(f"referrals/{cid}") or {}
    lines = ["👤 *My Referrals*\n━━━━━━━━━━━━━━━━━━━━━"]
    if not refs:
        lines.append("No referrals yet.\n\n📤 Share your link to start earning!")
    else:
        for i, (rid, rd) in enumerate(refs.items(), 1):
            st = "✅" if rd.get("status") == "verified" else "⏳"
            lines.append(
                f"{i}. {st} *{rd.get('name', 'User')}*\n"
                f"   💰 Earned: {fmt_coins(rd.get('earned', 0))}"
            )
    send_msg(cid, "\n".join(lines))

# ═══════════════════════════════════════════════════════════════════════════════
# RULES
# ═══════════════════════════════════════════════════════════════════════════════
@bot.message_handler(func=lambda m: m.text == "📋 Rules")
def msg_rules(msg):
    if not _guard(msg): return
    rules = RULES_TEXT()
    if not rules or rules == "📋 Rules coming soon.":
        rules = (
            "📋 *Game Rules*\n"
            "━━━━━━━━━━━━━━━━━━━━━\n"
            "🎮 *How to Play:*\n"
            "1️⃣ Wait for the live countdown to start\n"
            "2️⃣ Choose a colour: 🟢 Green, 🟣 Violet, or 🔴 Red\n"
            "3️⃣ Select your bet amount\n"
            "4️⃣ Wait for the result!\n\n"
            "💰 *Multipliers:*\n"
            "  🟢 Green → *1.9×*\n"
            "  🟣 Violet → *4.9×*\n"
            "  🔴 Red → *1.9×*\n\n"
            "⚠️ *Important:*\n"
            "• Only one bet per round\n"
            "• Bets cannot be cancelled after placing\n"
            "• Results are randomly generated\n"
            "• Minimum bet: 10 coins\n"
            "• Play responsibly!"
        )
    send_msg(str(msg.chat.id), rules)

# ═══════════════════════════════════════════════════════════════════════════════
# CUSTOMER SUPPORT
# ═══════════════════════════════════════════════════════════════════════════════
@bot.message_handler(func=lambda m: m.text == "📞 Customer Support")
def msg_support(msg):
    if not _guard(msg): return
    sup = SUPPORT_USERNAME()
    mk  = types.InlineKeyboardMarkup()
    mk.add(types.InlineKeyboardButton(
        "💬 Chat with Support",
        url=f"https://t.me/{sup.lstrip('@')}"
    ))
    send_msg(str(msg.chat.id),
        f"📞 *Customer Support*\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"🕐 Available: *24/7*\n"
        f"📬 Contact: *{sup}*\n\n"
        f"We can help with:\n"
        f"  • Deposit / withdrawal issues\n"
        f"  • Coin credit problems\n"
        f"  • Account help\n"
        f"  • Game queries\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"📝 Please have your *UTR/Ref number* ready.",
        reply_markup=mk)

# ═══════════════════════════════════════════════════════════════════════════════
# COLOUR PREDICTION — BET FLOW
# ═══════════════════════════════════════════════════════════════════════════════

# Step 1 — User clicks a colour button
@bot.callback_query_handler(func=lambda call: call.data.startswith("bet_"))
def handle_color_selection(call):
    parts = call.data.split("_")
    # Format: bet_{Color}_{order_id}
    selected_color = parts[1]
    order_id = "_".join(parts[2:])
    user_id  = call.from_user.id
    chat_id  = call.message.chat.id

    if order_id != current_order_id:
        bot.answer_callback_query(call.id, "⛔ This round has already closed!", show_alert=True)
        return

    with bet_lock:
        if user_id in current_bets:
            bot.answer_callback_query(call.id, "✋ You already placed a bet this round!", show_alert=True)
            return

    # Remove old amount menu if exists
    if user_id in active_menus:
        try: bot.delete_message(chat_id, active_menus[user_id])
        except: pass

    # Check user exists
    u = get_user(str(user_id))
    if not u:
        bot.answer_callback_query(call.id, "❌ Please send /start first!", show_alert=True)
        return

    wallet = u.get("wallet", 0)
    amounts = [10, 50, 100, 500, 1000]
    available = [a for a in amounts if a <= wallet]

    if not available:
        bot.answer_callback_query(call.id,
            f"❌ Insufficient coins! Balance: {wallet} 🪙", show_alert=True)
        return

    mk = types.InlineKeyboardMarkup()
    row1 = [types.InlineKeyboardButton(
        str(amt), callback_data=f"amt_{selected_color}_{amt}_{order_id}_{user_id}"
    ) for amt in available[:3]]
    row2 = [types.InlineKeyboardButton(
        str(amt), callback_data=f"amt_{selected_color}_{amt}_{order_id}_{user_id}"
    ) for amt in available[3:]]
    if row1: mk.row(*row1)
    if row2: mk.row(*row2)

    emoji = COLOR_EMOJIS.get(selected_color, "")
    msg = bot.send_message(
        chat_id,
        f"💰 *How much to bet on {selected_color} {emoji}?*\n"
        f"Your balance: *{fmt_coins(wallet)}*",
        reply_markup=mk,
        parse_mode="Markdown"
    )
    active_menus[user_id] = msg.message_id
    bot.answer_callback_query(call.id)

# Step 2 — User clicks an amount
@bot.callback_query_handler(func=lambda call: call.data.startswith("amt_"))
def handle_amount_selection(call):
    parts = call.data.split("_")
    # Format: amt_{color}_{amount}_{order_id}_{original_user_id}
    color          = parts[1]
    amount         = int(parts[2])
    order_id       = parts[3]
    orig_user_id   = int(parts[4])
    user_id        = call.from_user.id
    chat_id        = call.message.chat.id

    if user_id != orig_user_id:
        bot.answer_callback_query(call.id, "🚫 This is not your menu!", show_alert=True)
        return
    if order_id != current_order_id:
        bot.answer_callback_query(call.id, "⛔ Round already closed!", show_alert=True)
        try: bot.delete_message(chat_id, call.message.message_id)
        except: pass
        return

    with bet_lock:
        if user_id in current_bets:
            bot.answer_callback_query(call.id, "✋ Already placed!", show_alert=True)
            try: bot.delete_message(chat_id, call.message.message_id)
            except: pass
            return

        u = get_user(str(user_id))
        wallet = u.get("wallet", 0) if u else 0
        if wallet < amount:
            bot.answer_callback_query(call.id,
                f"❌ Insufficient coins! Balance: {wallet} 🪙", show_alert=True)
            try: bot.delete_message(chat_id, call.message.message_id)
            except: pass
            return

        # Deduct immediately
        fb.patch(f"users/{user_id}", {
            "wallet":       wallet - amount,
            "total_wagered": u.get("total_wagered", 0) + amount,
            "games_played":  u.get("games_played", 0) + 1,
        })
        current_bets[user_id] = {
            "color": color, "amount": amount, "chat_id": chat_id
        }
        active_menus.pop(user_id, None)

    bot.answer_callback_query(call.id, "✅ Bet placed!", show_alert=True)
    try: bot.delete_message(chat_id, call.message.message_id)
    except: pass

    emoji = COLOR_EMOJIS.get(color, "")
    bot.send_message(
        chat_id,
        f"✅ *Bet Placed!*\n"
        f"🎯 Colour: *{color} {emoji}*\n"
        f"💰 Amount: *{fmt_coins(amount)}*\n"
        f"⏳ Wait for the result!",
        parse_mode="Markdown"
    )

    # Log bet transaction
    bet_txn_id = f"BET_{order_id}_{user_id}"
    fb.put(f"users/{user_id}/transactions/{bet_txn_id}", {
        "type": "bet", "for": f"{color} {emoji}",
        "amount": -amount, "status": "pending", "date": now_str()
    })

# ═══════════════════════════════════════════════════════════════════════════════
# ANIMATED WIN/LOSS MEDIA (optional — requires ffmpeg)
# ═══════════════════════════════════════════════════════════════════════════════
def _get_gif_bytes(keyword):
    """Download a GIF from yesno.wtf and convert to square MP4 via ffmpeg."""
    force = "yes" if "win" in keyword else "no"
    try:
        url = requests.get(f"https://yesno.wtf/api?force={force}", timeout=5).json().get("image")
        if not url: return None
        resp = requests.get(url, timeout=10)
        with open("tmp_in.gif", "wb") as f: f.write(resp.content)
        subprocess.run([
            "ffmpeg", "-y", "-i", "tmp_in.gif",
            "-vf", r"crop=min(iw\,ih):min(iw\,ih),scale=320:320",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-an",
            "tmp_out.mp4"
        ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=30)
        with open("tmp_out.mp4", "rb") as f: data = f.read()
        for fn in ["tmp_in.gif", "tmp_out.mp4"]:
            if os.path.exists(fn): os.remove(fn)
        return data
    except Exception as e:
        print(f"[GIF] {e}"); return None

# ═══════════════════════════════════════════════════════════════════════════════
# 24/7 GAME LOOP
# ═══════════════════════════════════════════════════════════════════════════════
def run_game_loop():
    global current_order_id, current_bets, last_outcomes, active_menus

    print("🎮 Game loop started in 24/7 autopilot mode!")

    while True:
        try:
            # ── Reset round ──────────────────────────────────────────────────
            with bet_lock:
                current_bets.clear()
            active_menus.clear()
            active_messages.clear()

            current_order_id = "ORD" + "".join(random.choices(string.digits, k=10))

            # Build outcomes text
            if not last_outcomes:
                outcomes_text = "_No previous results yet_"
            else:
                formatted = []
                for i, outcome in enumerate(last_outcomes):
                    suffix = " *(latest)*" if i == len(last_outcomes) - 1 else ""
                    formatted.append(f"• {outcome}{suffix}")
                outcomes_text = "\n".join(formatted)

            # Betting buttons
            mk_bet = types.InlineKeyboardMarkup()
            mk_bet.row(
                types.InlineKeyboardButton("🟢 Green (1.9×)",  callback_data=f"bet_Green_{current_order_id}"),
                types.InlineKeyboardButton("🟣 Violet (4.9×)", callback_data=f"bet_Violet_{current_order_id}"),
                types.InlineKeyboardButton("🔴 Red (1.9×)",    callback_data=f"bet_Red_{current_order_id}"),
            )

            def _round_text(remaining):
                return (
                    f"🔴 🟣 🟢 *Colour Prediction* 🟢 🟣 🔴\n\n"
                    f"📋 Order: `{current_order_id}`\n"
                    f"⏳ Time: `{remaining}s`\n\n"
                    f"_Last Results:_\n{outcomes_text}\n\n"
                    f"👇 *Place your bet!*"
                )

            # ── Send opening message to all active users ──────────────────────
            for chat_id in list(active_users):
                try:
                    msg = bot.send_message(
                        chat_id, _round_text(60),
                        reply_markup=mk_bet, parse_mode="Markdown"
                    )
                    active_messages[chat_id] = msg.message_id
                except Exception as e:
                    print(f"[Game Loop] Remove {chat_id}: {e}")
                    active_users.discard(chat_id)

            # ── Countdown ─────────────────────────────────────────────────────
            for remaining in range(55, 0, -5):
                time.sleep(5)
                for chat_id, msg_id in list(active_messages.items()):
                    try:
                        bot.edit_message_text(
                            _round_text(remaining),
                            chat_id=chat_id, message_id=msg_id,
                            reply_markup=mk_bet, parse_mode="Markdown"
                        )
                    except: pass

            time.sleep(5)

            # ── Close round ───────────────────────────────────────────────────
            closed_text = (
                f"🔴 🟣 🟢 *Colour Prediction* 🟢 🟣 🔴\n\n"
                f"📋 Order: `{current_order_id}`\n"
                f"⏳ Time: `0s`\n\n"
                f"_Last Results:_\n{outcomes_text}\n\n"
                f"🛑 *Round Closed! Calculating result...*"
            )
            for chat_id, msg_id in list(active_messages.items()):
                try:
                    bot.edit_message_text(
                        closed_text, chat_id=chat_id, message_id=msg_id, parse_mode="Markdown"
                    )
                except: pass

            # ── Pick winner ───────────────────────────────────────────────────
            winning_color = random.choice(["Green", "Violet", "Red"])
            emoji = COLOR_EMOJIS[winning_color]

            # Pre-fetch media if needed
            with bet_lock:
                needs_win  = any(b["color"] == winning_color for b in current_bets.values())
                needs_loss = any(b["color"] != winning_color for b in current_bets.values())
            win_bytes  = _get_gif_bytes("win")  if needs_win  else None
            loss_bytes = _get_gif_bytes("loss") if needs_loss else None

            # ── Announce result to all ────────────────────────────────────────
            result_msg = (
                f"📊 *Result — {current_order_id}*\n"
                f"━━━━━━━━━━━━━━━━━━━━━\n"
                f"🏆 Winning Colour: *{winning_color} {emoji}*"
            )
            for chat_id in list(active_users):
                try: bot.send_message(chat_id, result_msg, parse_mode="Markdown")
                except: pass

            # ── Pay winners, notify losers ─────────────────────────────────────
            with bet_lock:
                for user_id, bet in current_bets.items():
                    u_color  = bet["color"]
                    u_amount = bet["amount"]
                    u_chat   = bet["chat_id"]
                    bet_txn_id = f"BET_{current_order_id}_{user_id}"

                    u = get_user(str(user_id))
                    wallet = u.get("wallet", 0) if u else 0

                    if u_color == winning_color:
                        mult     = MULTIPLIERS[winning_color]
                        winnings = int(u_amount * mult)
                        profit   = winnings - u_amount

                        # Credit wallet
                        fb.patch(f"users/{user_id}", {
                            "wallet":    wallet + winnings,
                            "total_won": u.get("total_won", 0) + winnings,
                            "games_won": u.get("games_won", 0) + 1,
                        })
                        # Update bet transaction
                        fb.patch(f"users/{user_id}/transactions/{bet_txn_id}", {
                            "status": "success"
                        })
                        # Log win transaction
                        win_txn = f"WIN_{current_order_id}_{user_id}"
                        fb.put(f"users/{user_id}/transactions/{win_txn}", {
                            "type": "win", "for": f"{u_color} {COLOR_EMOJIS[u_color]}",
                            "amount": winnings, "status": "success", "date": now_str()
                        })

                        caption = (
                            f"🎉 *YOU WON!* 🎉\n"
                            f"━━━━━━━━━━━━━━━━━━━━━\n"
                            f"🎯 Colour: *{u_color} {COLOR_EMOJIS[u_color]}*\n"
                            f"💰 Bet: *{fmt_coins(u_amount)}*\n"
                            f"✨ Multiplier: *{mult}×*\n"
                            f"🏆 Winnings: *+{fmt_coins(winnings)}*\n"
                            f"💵 Profit: *+{fmt_coins(profit)}*\n"
                            f"👛 New Balance: *{fmt_coins(wallet + winnings)}*"
                        )
                        if win_bytes:
                            try:
                                s = io.BytesIO(win_bytes); s.name = "win.mp4"
                                bot.send_animation(u_chat, s, caption=caption, parse_mode="Markdown")
                                continue
                            except: pass
                        bot.send_message(u_chat, caption, parse_mode="Markdown")

                    else:
                        fb.patch(f"users/{user_id}/transactions/{bet_txn_id}", {"status": "failed"})

                        caption = (
                            f"😢 *Better luck next time!*\n"
                            f"━━━━━━━━━━━━━━━━━━━━━\n"
                            f"🎯 Your choice: *{u_color} {COLOR_EMOJIS[u_color]}*\n"
                            f"💔 Winning: *{winning_color} {emoji}*\n"
                            f"📉 Lost: *{fmt_coins(u_amount)}*\n"
                            f"👛 Balance: *{fmt_coins(wallet)}*"
                        )
                        if loss_bytes:
                            try:
                                s = io.BytesIO(loss_bytes); s.name = "loss.mp4"
                                bot.send_animation(u_chat, s, caption=caption, parse_mode="Markdown")
                                continue
                            except: pass
                        bot.send_message(u_chat, caption, parse_mode="Markdown")

            # ── Update history ────────────────────────────────────────────────
            last_outcomes.append(f"{winning_color} {emoji}")
            if len(last_outcomes) > 5:
                last_outcomes.pop(0)
            # Persist to Firebase
            try: fb.put("game_history/last_outcomes", last_outcomes)
            except: pass

            time.sleep(5)  # Short pause before next round

        except Exception as e:
            print(f"[Game Loop Error] {e}")
            time.sleep(15)


# ═══════════════════════════════════════════════════════════════════════════════
# ADMIN: Credit deposit (called externally or via admin panel)
# ═══════════════════════════════════════════════════════════════════════════════
def admin_credit_deposit(dep_id: str, approved: bool):
    """
    Called by admin panel to approve/reject a deposit request.
    Approves → credits wallet. Rejects → notifies user.
    """
    req = fb.get(f"deposit_requests/{dep_id}")
    if not req: return False, "Deposit request not found"
    if req.get("status") != "pending":
        return False, f"Already processed: {req.get('status')}"

    cid   = req.get("chat_id")
    coins = int(req.get("coins", 0))
    price = int(req.get("price", 0))

    if approved:
        u = get_user(cid)
        new_bal = u.get("wallet", 0) + coins if u else coins
        fb.patch(f"users/{cid}", {
            "wallet": new_bal,
            "total_deposited": (u.get("total_deposited", 0) if u else 0) + coins,
        })
        fb.patch(f"deposit_requests/{dep_id}", {"status": "approved", "updated_at": now_str()})
        fb.patch(f"users/{cid}/transactions/{dep_id}", {"status": "success"})

        # Referral commission on deposit
        if u:
            referred_by = u.get("referred_by", "")
            if referred_by:
                comm_pct = REFER_COMMISSION()
                earned   = round(coins * comm_pct / 100, 0)
                ref_u    = get_user(referred_by)
                if ref_u and earned > 0:
                    fb.patch(f"users/{referred_by}", {
                        "wallet":         ref_u.get("wallet", 0) + earned,
                        "total_earned":   ref_u.get("total_earned", 0) + earned,
                        "verified_refer": ref_u.get("verified_refer", 0) + 1,
                        "pending_refer":  max(0, ref_u.get("pending_refer", 0) - 1),
                    })
                    fb.put(f"users/{referred_by}/transactions/REF_{dep_id}", {
                        "type": "referral", "for": u.get("full_name", "User"),
                        "amount": earned, "status": "success", "date": now_str()
                    })
                    fb.patch(f"referrals/{referred_by}/{cid}", {
                        "status": "verified",
                        "earned": ref_u.get("earned", 0) + earned
                    })
                    send_msg(referred_by,
                        f"💸 *Referral Commission!*\n"
                        f"━━━━━━━━━━━━━━━━━━━━━\n"
                        f"👤 *{u.get('full_name', 'Your referral')}* deposited ₹{price:,}\n"
                        f"💰 You earned: *{fmt_coins(earned)}*\n"
                        f"👛 New Balance: *{fmt_coins(ref_u.get('wallet', 0) + earned)}*")

        send_msg(cid,
            f"✅ *Deposit Approved!*\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n"
            f"💰 *{fmt_coins(coins)}* have been credited to your wallet!\n"
            f"🔖 Ref: `{dep_id}`\n"
            f"👛 Balance: *{fmt_coins(new_bal)}*\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n"
            f"🎮 Good luck in the game!",
            reply_markup=kb_main())
        return True, "Approved"
    else:
        fb.patch(f"deposit_requests/{dep_id}", {"status": "rejected", "updated_at": now_str()})
        fb.patch(f"users/{cid}/transactions/{dep_id}", {"status": "failed"})
        send_msg(cid,
            f"❌ *Deposit Rejected*\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n"
            f"Your deposit request `{dep_id}` (₹{price:,}) was not verified.\n\n"
            f"📞 Please contact support if you believe this is an error.",
            reply_markup=kb_main())
        return True, "Rejected"


# ═══════════════════════════════════════════════════════════════════════════════
# BROADCAST (for admin panel)
# ═══════════════════════════════════════════════════════════════════════════════
def broadcast_message(text=None, image_url=None, chat_ids=None):
    if not chat_ids:
        users = fb.get("users") or {}
        chat_ids = list(users.keys())
    ok = fail = 0
    for cid in chat_ids:
        try:
            if image_url and text:
                bot.send_photo(cid, image_url, caption=text, parse_mode="Markdown")
            elif image_url:
                bot.send_photo(cid, image_url)
            elif text:
                bot.send_message(cid, text, parse_mode="Markdown")
            ok += 1
            time.sleep(0.05)
        except Exception as e:
            print(f"[Broadcast] {cid}: {e}"); fail += 1
    return ok, fail


# ═══════════════════════════════════════════════════════════════════════════════
# ENTRY POINT
# ═══════════════════════════════════════════════════════════════════════════════
def run_bot():
    if not bot:
        print("❌ Bot not started — BOT_TOKEN missing"); return

    # Restore last_outcomes from Firebase
    global last_outcomes
    saved = fb.get("game_history/last_outcomes")
    if isinstance(saved, list):
        last_outcomes = saved

    print("🎮 Starting 24/7 game loop thread...")
    game_thread = threading.Thread(target=run_game_loop, daemon=True)
    game_thread.start()

    print("🤖 Bot polling started. Send /start to join!")
    bot.infinity_polling(timeout=30, long_polling_timeout=30)


if __name__ == "__main__":
    run_bot()
