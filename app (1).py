"""
app.py — Flask Admin Panel for ColourBot
Access at /admin after setting ADMIN_USERNAME + ADMIN_PASSWORD in env/Firebase.
"""
from flask import (Flask, render_template, redirect, url_for,
                   request, session, jsonify, flash)
import firebase_helper as fb
import bot as game_bot
from config import (SECRET_KEY, FLASK_PORT, PANEL_NAME, PANEL_COPYRIGHT,
                    ADMIN_USERNAME, ADMIN_PASSWORD)
import datetime, os

app = Flask(__name__)
app.secret_key = SECRET_KEY

def now_str(): return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
def fmt_coins(n):
    try: return f"{int(n):,}"
    except: return str(n)

def _check_login():
    return session.get("admin_logged_in") is True

# ── Auth ──────────────────────────────────────────────────────────────────────
@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    if request.method == "POST":
        if (request.form.get("username") == ADMIN_USERNAME() and
                request.form.get("password") == ADMIN_PASSWORD()):
            session["admin_logged_in"] = True
            return redirect(url_for("admin_dashboard"))
        flash("❌ Invalid credentials", "danger")
    return render_template("login.html",
                           panel_name=PANEL_NAME(),
                           copyright=PANEL_COPYRIGHT())

@app.route("/admin/logout")
def admin_logout():
    session.clear()
    return redirect(url_for("admin_login"))

# ── Dashboard ─────────────────────────────────────────────────────────────────
@app.route("/admin")
@app.route("/admin/dashboard")
def admin_dashboard():
    if not _check_login(): return redirect(url_for("admin_login"))
    users     = fb.get("users") or {}
    dep_reqs  = fb.get("deposit_requests") or {}
    withdraws = fb.get("withdrawals") or {}

    total_users    = len(users)
    total_wallet   = sum(u.get("wallet", 0) for u in users.values())
    pending_deps   = sum(1 for d in dep_reqs.values()  if d.get("status") == "pending")
    pending_wds    = sum(1 for w in withdraws.values() if w.get("status") == "pending")
    outcomes       = fb.get("game_history/last_outcomes") or []

    return render_template("dashboard.html",
        panel_name=PANEL_NAME(), copyright=PANEL_COPYRIGHT(),
        total_users=total_users, total_wallet=fmt_coins(total_wallet),
        pending_deps=pending_deps, pending_wds=pending_wds,
        last_outcomes=outcomes)

# ── Deposits ──────────────────────────────────────────────────────────────────
@app.route("/admin/deposits")
def admin_deposits():
    if not _check_login(): return redirect(url_for("admin_login"))
    deps = fb.get("deposit_requests") or {}
    items = sorted(deps.items(), key=lambda x: x[1].get("created_at",""), reverse=True)
    return render_template("deposits.html",
        panel_name=PANEL_NAME(), copyright=PANEL_COPYRIGHT(),
        deposits=items)

@app.route("/admin/deposits/action", methods=["POST"])
def admin_deposit_action():
    if not _check_login(): return redirect(url_for("admin_login"))
    dep_id   = request.form.get("dep_id")
    action   = request.form.get("action")  # "approve" or "reject"
    approved = (action == "approve")
    ok, msg  = game_bot.admin_credit_deposit(dep_id, approved)
    flash(f"{'✅' if ok else '❌'} {msg}", "success" if ok else "danger")
    return redirect(url_for("admin_deposits"))

# ── Withdrawals ────────────────────────────────────────────────────────────────
@app.route("/admin/withdrawals")
def admin_withdrawals():
    if not _check_login(): return redirect(url_for("admin_login"))
    wds = fb.get("withdrawals") or {}
    items = sorted(wds.items(), key=lambda x: x[1].get("created_at",""), reverse=True)
    return render_template("withdrawals.html",
        panel_name=PANEL_NAME(), copyright=PANEL_COPYRIGHT(),
        withdrawals=items)

@app.route("/admin/withdrawals/action", methods=["POST"])
def admin_withdrawal_action():
    if not _check_login(): return redirect(url_for("admin_login"))
    wd_id  = request.form.get("wd_id")
    action = request.form.get("action")  # "complete" or "reject"
    wd     = fb.get(f"withdrawals/{wd_id}")
    if not wd:
        flash("❌ Not found", "danger")
        return redirect(url_for("admin_withdrawals"))
    cid    = wd.get("chat_id")
    amount = wd.get("amount", 0)
    if action == "complete":
        fb.patch(f"withdrawals/{wd_id}", {"status": "completed", "updated_at": now_str()})
        fb.patch(f"users/{cid}/transactions/{wd_id}", {"status": "success"})
        game_bot.send_msg(cid,
            f"✅ *Withdrawal Processed!*\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n"
            f"🪙 {fmt_coins(amount)} coins withdrawal completed.\n"
            f"🔖 ID: `{wd_id}`")
        flash("✅ Marked as completed", "success")
    elif action == "reject":
        # Refund coins
        u = fb.get(f"users/{cid}")
        if u:
            fb.patch(f"users/{cid}", {"wallet": u.get("wallet", 0) + amount})
        fb.patch(f"withdrawals/{wd_id}", {"status": "rejected", "updated_at": now_str()})
        fb.patch(f"users/{cid}/transactions/{wd_id}", {"status": "failed"})
        game_bot.send_msg(cid,
            f"❌ *Withdrawal Rejected*\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n"
            f"🪙 {fmt_coins(amount)} coins have been refunded.\n"
            f"📞 Contact support for details.")
        flash("❌ Rejected and coins refunded", "warning")
    return redirect(url_for("admin_withdrawals"))

# ── Users ─────────────────────────────────────────────────────────────────────
@app.route("/admin/users")
def admin_users():
    if not _check_login(): return redirect(url_for("admin_login"))
    users = fb.get("users") or {}
    items = sorted(users.items(), key=lambda x: x[1].get("created_at",""), reverse=True)
    return render_template("users.html",
        panel_name=PANEL_NAME(), copyright=PANEL_COPYRIGHT(),
        users=items)

@app.route("/admin/users/edit/<cid>", methods=["GET", "POST"])
def admin_edit_user(cid):
    if not _check_login(): return redirect(url_for("admin_login"))
    u = fb.get(f"users/{cid}")
    if not u: flash("❌ User not found", "danger"); return redirect(url_for("admin_users"))
    if request.method == "POST":
        new_wallet = request.form.get("wallet", u.get("wallet", 0))
        try: new_wallet = int(new_wallet)
        except: new_wallet = u.get("wallet", 0)
        fb.patch(f"users/{cid}", {"wallet": new_wallet})
        flash(f"✅ Wallet updated to {fmt_coins(new_wallet)} coins", "success")
        return redirect(url_for("admin_users"))
    return render_template("edit_user.html",
        panel_name=PANEL_NAME(), copyright=PANEL_COPYRIGHT(),
        user=u, cid=cid)

# ── Payment Info ──────────────────────────────────────────────────────────────
@app.route("/admin/payment-info", methods=["GET", "POST"])
def admin_payment_info():
    if not _check_login(): return redirect(url_for("admin_login"))
    if request.method == "POST":
        fb.put("payment_info", {
            "upi_id":  request.form.get("upi_id", "").strip(),
            "name":    request.form.get("name", "").strip(),
            "qr_url":  request.form.get("qr_url", "").strip(),
        })
        flash("✅ Payment info updated!", "success")
    info = fb.get("payment_info") or {}
    return render_template("payment_info.html",
        panel_name=PANEL_NAME(), copyright=PANEL_COPYRIGHT(),
        info=info)

# ── Deposit Packages ──────────────────────────────────────────────────────────
@app.route("/admin/packages", methods=["GET", "POST"])
def admin_packages():
    if not _check_login(): return redirect(url_for("admin_login"))
    if request.method == "POST":
        action = request.form.get("action")
        if action == "add":
            pkg_id = f"pkg{int(datetime.datetime.now().timestamp())}"
            fb.put(f"deposit_packages/{pkg_id}", {
                "label": request.form.get("label","").strip(),
                "coins": int(request.form.get("coins", 0)),
                "price": int(request.form.get("price", 0)),
                "bonus": int(request.form.get("bonus", 0)),
            })
            flash("✅ Package added!", "success")
        elif action == "delete":
            pkg_id = request.form.get("pkg_id")
            fb.delete(f"deposit_packages/{pkg_id}")
            flash("🗑️ Package deleted", "warning")
    packages = fb.get("deposit_packages") or {}
    return render_template("packages.html",
        panel_name=PANEL_NAME(), copyright=PANEL_COPYRIGHT(),
        packages=packages.items())

# ── Settings ──────────────────────────────────────────────────────────────────
@app.route("/admin/settings", methods=["GET", "POST"])
def admin_settings():
    if not _check_login(): return redirect(url_for("admin_login"))
    if request.method == "POST":
        updates = {
            "bot_username":    request.form.get("bot_username","").strip(),
            "support_username":request.form.get("support_username","").strip(),
            "rules_text":      request.form.get("rules_text","").strip(),
            "signup_bonus":    request.form.get("signup_bonus","50").strip(),
            "min_deposit":     request.form.get("min_deposit","100").strip(),
            "min_withdrawal":  request.form.get("min_withdrawal","100").strip(),
            "max_withdrawal":  request.form.get("max_withdrawal","50000").strip(),
            "refer_commission":request.form.get("refer_commission","5").strip(),
            "notify_chat_ids": request.form.get("notify_chat_ids","").strip(),
            "panel_name":      request.form.get("panel_name","").strip(),
            "admin_username":  request.form.get("admin_username","").strip(),
            "admin_password":  request.form.get("admin_password","").strip(),
        }
        fb.patch("config", updates)
        flash("✅ Settings saved!", "success")
    cfg = fb.get("config") or {}
    return render_template("settings.html",
        panel_name=PANEL_NAME(), copyright=PANEL_COPYRIGHT(),
        cfg=cfg)

# ── Broadcast ─────────────────────────────────────────────────────────────────
@app.route("/admin/broadcast", methods=["GET", "POST"])
def admin_broadcast():
    if not _check_login(): return redirect(url_for("admin_login"))
    result = None
    if request.method == "POST":
        text      = request.form.get("text","").strip()
        image_url = request.form.get("image_url","").strip()
        ok, fail  = game_bot.broadcast_message(
            text=text or None,
            image_url=image_url or None
        )
        result = {"ok": ok, "fail": fail}
        flash(f"✅ Sent to {ok} users ({fail} failed)", "success")
    return render_template("broadcast.html",
        panel_name=PANEL_NAME(), copyright=PANEL_COPYRIGHT(),
        result=result)

# ── Referrals ─────────────────────────────────────────────────────────────────
@app.route("/admin/referrals")
def admin_referrals():
    if not _check_login(): return redirect(url_for("admin_login"))
    users = fb.get("users") or {}
    rows = []
    for uid, u in users.items():
        if u.get("refer_count", 0) > 0:
            rows.append({
                "chat_id":   uid,
                "name":      u.get("full_name",""),
                "count":     u.get("refer_count", 0),
                "verified":  u.get("verified_refer", 0),
                "earned":    u.get("total_earned", 0),
            })
    rows.sort(key=lambda x: x["count"], reverse=True)
    return render_template("referrals.html",
        panel_name=PANEL_NAME(), copyright=PANEL_COPYRIGHT(),
        referrals=rows)

# ── Run ────────────────────────────────────────────────────────────────────────
def run_flask():
    app.run(host="0.0.0.0", port=FLASK_PORT)

if __name__ == "__main__":
    run_flask()
