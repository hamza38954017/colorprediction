# 🎮 ColourPredict Telegram Bot

A 24/7 automated colour prediction game bot with wallet management, manual deposit system, referral program, and a web-based admin panel — all powered by Firebase Realtime Database.

---

## ✨ Features

| Feature | Description |
|---|---|
| 🎮 24/7 Game Loop | Automated colour prediction every 60 seconds |
| 💰 Wallet System | Coin-based wallet stored in Firebase |
| 📥 Manual Deposit | Coin packages → QR/UPI → UTR verification |
| 📤 Withdrawal | Request via UPI ID, admin approves |
| 💳 Transactions | Full history of bets, deposits, wins, referrals |
| 👥 Refer & Earn | Referral links with % commission on deposits |
| 📋 Rules | Configurable from admin panel |
| 📞 Support | Direct link to support username |
| 🌐 Admin Panel | Flask web panel for approvals, settings, packages |
| 📢 Broadcast | Send message/image to all users |

---

## 🗂 File Structure

```
colourbot/
├── bot.py              # Telegram bot — game logic + all handlers
├── app.py              # Flask admin panel
├── main.py             # Entry point (runs both together)
├── config.py           # Config helpers reading from Firebase
├── firebase_helper.py  # Pure REST Firebase client
├── requirements.txt
├── Procfile            # For Render/Heroku
├── render.yaml         # One-click Render deploy
└── templates/
    ├── base.html
    ├── login.html
    ├── dashboard.html
    ├── deposits.html
    ├── withdrawals.html
    ├── users.html
    ├── edit_user.html
    ├── packages.html
    ├── payment_info.html
    ├── referrals.html
    ├── broadcast.html
    └── settings.html
```

---

## 🚀 Setup Guide

### Step 1 — Create a Telegram Bot

1. Open Telegram and search for `@BotFather`
2. Send `/newbot` and follow prompts
3. Copy the **Bot Token** (looks like `123456789:ABCdef...`)

---

### Step 2 — Set Up Firebase

1. Go to [console.firebase.google.com](https://console.firebase.google.com)
2. Click **Add Project** → give it a name → Continue
3. Go to **Build → Realtime Database → Create Database**
4. Choose a region → Start in **Test Mode** (you'll secure it later)
5. Copy the **Database URL** (e.g. `https://your-project-default-rtdb.firebaseio.com`)
6. Go to **Project Settings → Service Accounts → Database Secrets**
7. Click **Show** and copy the **Legacy Secret**

---

### Step 3 — Seed Firebase Config

In your Firebase Realtime Database, manually add these nodes (or the bot will use defaults):

```json
{
  "config": {
    "bot_username": "YourBotUsername",
    "support_username": "@YourSupportUsername",
    "rules_text": "📋 *Game Rules*\n\n1. Predict the colour\n2. Win multiplied coins!",
    "signup_bonus": 50,
    "min_deposit": 100,
    "min_withdrawal": 100,
    "max_withdrawal": 50000,
    "refer_commission": 5,
    "notify_chat_ids": "YOUR_ADMIN_CHAT_ID",
    "panel_name": "ColourBot Admin",
    "admin_username": "admin",
    "admin_password": "yourpassword123"
  },
  "payment_info": {
    "upi_id": "yourname@upi",
    "name": "Your Name",
    "qr_url": "https://link-to-your-qr-code-image.jpg"
  }
}
```

> **How to add data in Firebase:** Click the **+** icon next to the root node, enter key and value.

---

### Step 4 — Set Up Deposit Packages

In Firebase, add the `deposit_packages` node:

```json
{
  "deposit_packages": {
    "pkg1": { "label": "Starter",  "coins": 100,  "price": 100,  "bonus": 0   },
    "pkg2": { "label": "Popular",  "coins": 550,  "price": 500,  "bonus": 50  },
    "pkg3": { "label": "Value",    "coins": 1200, "price": 1000, "bonus": 200 },
    "pkg4": { "label": "Premium",  "coins": 2700, "price": 2000, "bonus": 700 },
    "pkg5": { "label": "VIP",      "coins": 7000, "price": 5000, "bonus": 2000}
  }
}
```

You can also manage packages from the **Admin Panel → Packages** tab.

---

### Step 5 — Deploy to Render (Recommended — Free)

1. Push this folder to a **GitHub repository**
2. Go to [render.com](https://render.com) → New → Web Service
3. Connect your GitHub repo
4. Fill in environment variables:

| Variable | Value |
|---|---|
| `BOT_TOKEN` | Your Telegram bot token |
| `FIREBASE_URL` | `https://your-project-default-rtdb.firebaseio.com` |
| `FIREBASE_SECRET` | Your Firebase legacy secret |
| `ADMIN_USERNAME` | Your admin panel username |
| `ADMIN_PASSWORD` | Your admin panel password |
| `SECRET_KEY` | Any random string (e.g. `abc123xyz`) |

5. Set **Start Command** to: `python main.py`
6. Click **Deploy**

Your admin panel will be at: `https://your-app.onrender.com/admin`

---

### Step 6 — Run Locally (Development)

```bash
# Install dependencies
pip install -r requirements.txt

# Set environment variables
export BOT_TOKEN="your_bot_token"
export FIREBASE_URL="https://your-project.firebaseio.com"
export FIREBASE_SECRET="your_firebase_secret"
export ADMIN_USERNAME="admin"
export ADMIN_PASSWORD="admin123"

# Run
python main.py
```

---

## 🎮 How the Game Works

1. Every **60 seconds**, the bot sends a live countdown to all active users
2. Users click **🟢 Green**, **🟣 Violet**, or **🔴 Red**
3. Users select a **bet amount** (10 / 50 / 100 / 500 / 1000 coins)
4. At 0s, a random colour is picked and payouts are made:
   - 🟢 Green / 🔴 Red → **1.9×** your bet
   - 🟣 Violet → **4.9×** your bet
5. Win/loss animations are sent (requires `ffmpeg` installed on server)

---

## 💰 Deposit Flow (User Side)

1. User taps **💰 Wallet** → **➕ Deposit Coins**
2. Bot shows coin packages (fetched from Firebase)
3. User selects a package → bot shows **QR code + UPI ID + amount**
4. User pays via UPI app
5. User enters their **12-digit UTR / Reference Number**
6. Bot saves the request → tells user: *"Verification takes up to 1 hour"*
7. Admin approves in panel → coins credited automatically

---

## 🌐 Admin Panel

Access at: `https://your-domain.com/admin`

| Page | Function |
|---|---|
| Dashboard | Stats + last game results |
| Deposits | Approve / reject deposit requests |
| Withdrawals | Complete / reject withdrawal requests |
| Users | View all users, edit wallet balance |
| Packages | Add/delete coin packages |
| Payment Info | Update UPI ID, name, QR code |
| Referrals | Leaderboard of top referrers |
| Broadcast | Send message to all users |
| Settings | Bot config, limits, commission |

---

## 📱 Bot Menu Buttons

| Button | Function |
|---|---|
| 🏠 Home | Profile & stats overview |
| 💰 Wallet | Balance + deposit + withdraw |
| 💳 Transactions | Last 15 transactions |
| 👥 Refer & Earn | Referral link + stats |
| 👤 My Refer | List of your referrals |
| 📋 Rules | Game rules |
| 📞 Customer Support | Support chat link |

---

## 📦 Firebase Data Structure

```
/
├── config/               ← Bot settings (live-editable)
├── users/
│   └── {chat_id}/
│       ├── wallet
│       ├── refer_code
│       ├── referred_by
│       └── transactions/
│           └── {txn_id}
├── deposit_packages/     ← Coin packages shown to users
├── payment_info/         ← UPI + QR code
├── deposit_requests/     ← Pending manual deposits
├── withdrawals/          ← Withdrawal requests
├── referrals/
│   └── {referrer_id}/{referred_id}
├── refer_codes/          ← Code → chat_id lookup
├── game_history/
│   └── last_outcomes     ← Last 5 results
└── user_temp/            ← State persistence across restarts
```

---

## ⚙️ Optional: Win/Loss Animations

The bot can send animated GIF reactions on win/loss. This requires `ffmpeg`:

```bash
# Ubuntu/Debian
sudo apt install ffmpeg

# macOS
brew install ffmpeg
```

If `ffmpeg` is not available, the bot gracefully falls back to text messages.

---

## 🔒 Security Notes

- Change the default `ADMIN_PASSWORD` immediately
- Use a strong `SECRET_KEY` for Flask sessions
- In Firebase, update Realtime Database rules after testing:
  ```json
  {
    "rules": {
      ".read": false,
      ".write": false
    }
  }
  ```
  (The bot uses the secret key to authenticate)

---

## 📞 Support

Configure the support username in **Admin Panel → Settings → Support Username**.

Users tap **📞 Customer Support** → a button opens the Telegram support chat.

---

*Built with pyTelegramBotAPI + Flask + Firebase Realtime Database*
