#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
UZCoin Telegram Bot
Muallif: UZCoin Team
Versiya: 1.0.0
Pydroid3 uchun tayyor
"""

import telebot
from telebot import types
import sqlite3
import time
import datetime
import threading

# ============================================================
#  ⚙️ KONFIGURATSIYA — Shu yerda o'zgartiring
# ============================================================
BOT_TOKEN = "8739570424:AAFkGtVG86YCTFr5TXokGcqmgzMJm5OzCKQ"          # @BotFather dan olingan token
ADMIN_IDS = [7174867537]                    # Admin Telegram ID-lari ro'yxati
BOT_USERNAME = "Oz_coin_bot"         # Botning username (@ siz)
DB_PATH = "bot.db"                         # SQLite fayl nomi
DAILY_BONUS_AMOUNT = 1                    # Kunlik bonus miqdori (UZCoin)
REFERRAL_BONUS = 5                         # Referal uchun bonus (UZCoin)
MIN_WITHDRAW = 50                          # Minimal yechish miqdori
# ============================================================

bot = telebot.TeleBot(BOT_TOKEN, parse_mode="HTML")

# ============================================================
#  🗄 DATABASE
# ============================================================

def get_db():
    """Thread-safe SQLite ulanish qaytaradi."""
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    """Jadvallarni yaratadi (mavjud bo'lsa o'zgartirmaydi)."""
    conn = get_db()
    cur = conn.cursor()

    cur.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            user_id     INTEGER PRIMARY KEY,
            username    TEXT,
            full_name   TEXT,
            balance     REAL    DEFAULT 0,
            referrer_id INTEGER DEFAULT NULL,
            joined_at   TEXT    DEFAULT (datetime('now','localtime'))
        );

        CREATE TABLE IF NOT EXISTS referrals (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            referrer_id INTEGER NOT NULL,
            referred_id INTEGER NOT NULL,
            bonus       REAL    DEFAULT 5,
            created_at  TEXT    DEFAULT (datetime('now','localtime')),
            UNIQUE(referred_id)
        );

        CREATE TABLE IF NOT EXISTS withdraws (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id     INTEGER NOT NULL,
            amount      REAL    NOT NULL,
            wallet_info TEXT    NOT NULL,
            status      TEXT    DEFAULT 'pending',
            created_at  TEXT    DEFAULT (datetime('now','localtime')),
            resolved_at TEXT    DEFAULT NULL
        );

        CREATE TABLE IF NOT EXISTS bonus (
            user_id     INTEGER PRIMARY KEY,
            last_claim  TEXT    DEFAULT NULL
        );

        CREATE TABLE IF NOT EXISTS channels (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            channel_id  TEXT    NOT NULL UNIQUE,
            channel_name TEXT   NOT NULL,
            invite_link TEXT    NOT NULL
        );
    """)
    conn.commit()
    conn.close()

init_db()

# ============================================================
#  🔧 YORDAMCHI FUNKSIYALAR
# ============================================================

def register_user(user_id: int, username: str, full_name: str, referrer_id: int = None):
    conn = get_db()
    cur = conn.cursor()
    try:
        cur.execute(
            "INSERT OR IGNORE INTO users (user_id, username, full_name, referrer_id) VALUES (?,?,?,?)",
            (user_id, username, full_name, referrer_id)
        )
        if cur.rowcount > 0 and referrer_id:
            # Referral bonusi
            cur.execute(
                "INSERT OR IGNORE INTO referrals (referrer_id, referred_id, bonus) VALUES (?,?,?)",
                (referrer_id, user_id, REFERRAL_BONUS)
            )
            cur.execute(
                "UPDATE users SET balance = balance + ? WHERE user_id = ?",
                (REFERRAL_BONUS, referrer_id)
            )
        conn.commit()
        return cur.rowcount > 0  # True = yangi foydalanuvchi
    except Exception as e:
        print(f"[register_user] Xato: {e}")
        return False
    finally:
        conn.close()

def get_user(user_id: int):
    conn = get_db()
    cur = conn.cursor()
    try:
        cur.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
        return cur.fetchone()
    finally:
        conn.close()

def get_balance(user_id: int) -> float:
    user = get_user(user_id)
    return user["balance"] if user else 0.0

def add_balance(user_id: int, amount: float):
    conn = get_db()
    try:
        conn.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (amount, user_id))
        conn.commit()
    finally:
        conn.close()

def set_balance(user_id: int, amount: float):
    conn = get_db()
    try:
        conn.execute("UPDATE users SET balance = ? WHERE user_id = ?", (amount, user_id))
        conn.commit()
    finally:
        conn.close()

def get_referral_count(user_id: int) -> int:
    conn = get_db()
    try:
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM referrals WHERE referrer_id = ?", (user_id,))
        return cur.fetchone()[0]
    finally:
        conn.close()

def get_total_users() -> int:
    conn = get_db()
    try:
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM users")
        return cur.fetchone()[0]
    finally:
        conn.close()

def get_all_user_ids():
    conn = get_db()
    try:
        cur = conn.cursor()
        cur.execute("SELECT user_id FROM users")
        return [row[0] for row in cur.fetchall()]
    finally:
        conn.close()

def get_top_referrers(limit: int = 10):
    conn = get_db()
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT u.user_id, u.full_name, u.username, COUNT(r.referred_id) as ref_count
            FROM users u
            LEFT JOIN referrals r ON u.user_id = r.referrer_id
            GROUP BY u.user_id
            ORDER BY ref_count DESC
            LIMIT ?
        """, (limit,))
        return cur.fetchall()
    finally:
        conn.close()

# --- Kunlik bonus ---
def can_claim_bonus(user_id: int) -> bool:
    conn = get_db()
    try:
        cur = conn.cursor()
        cur.execute("SELECT last_claim FROM bonus WHERE user_id = ?", (user_id,))
        row = cur.fetchone()
        if not row or not row["last_claim"]:
            return True
        last = datetime.datetime.fromisoformat(row["last_claim"])
        now = datetime.datetime.now()
        return (now - last).total_seconds() >= 86400
    finally:
        conn.close()

def claim_bonus(user_id: int):
    conn = get_db()
    try:
        now_str = datetime.datetime.now().isoformat()
        conn.execute(
            "INSERT INTO bonus (user_id, last_claim) VALUES (?,?) ON CONFLICT(user_id) DO UPDATE SET last_claim=?",
            (user_id, now_str, now_str)
        )
        conn.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (DAILY_BONUS_AMOUNT, user_id))
        conn.commit()
    finally:
        conn.close()

def next_bonus_time(user_id: int) -> str:
    conn = get_db()
    try:
        cur = conn.cursor()
        cur.execute("SELECT last_claim FROM bonus WHERE user_id = ?", (user_id,))
        row = cur.fetchone()
        if not row or not row["last_claim"]:
            return "Hozir olishingiz mumkin!"
        last = datetime.datetime.fromisoformat(row["last_claim"])
        nxt = last + datetime.timedelta(days=1)
        diff = nxt - datetime.datetime.now()
        h, rem = divmod(int(diff.total_seconds()), 3600)
        m = rem // 60
        return f"{h} soat {m} daqiqa"
    finally:
        conn.close()

# --- Channels ---
def get_channels():
    conn = get_db()
    try:
        cur = conn.cursor()
        cur.execute("SELECT * FROM channels")
        return cur.fetchall()
    finally:
        conn.close()

def add_channel(channel_id: str, channel_name: str, invite_link: str):
    conn = get_db()
    try:
        conn.execute(
            "INSERT OR IGNORE INTO channels (channel_id, channel_name, invite_link) VALUES (?,?,?)",
            (channel_id, channel_name, invite_link)
        )
        conn.commit()
        return True
    except:
        return False
    finally:
        conn.close()

def remove_channel(channel_id: str):
    conn = get_db()
    try:
        conn.execute("DELETE FROM channels WHERE channel_id = ?", (channel_id,))
        conn.commit()
    finally:
        conn.close()

def check_subscription(user_id: int) -> list:
    """A'zo bo'lmagan kanallar ro'yxatini qaytaradi."""
    channels = get_channels()
    not_subscribed = []
    for ch in channels:
        try:
            member = bot.get_chat_member(ch["channel_id"], user_id)
            if member.status in ["left", "kicked", "banned"]:
                not_subscribed.append(ch)
        except Exception:
            not_subscribed.append(ch)
    return not_subscribed

# --- Withdraws ---
def create_withdraw(user_id: int, amount: float, wallet_info: str):
    conn = get_db()
    try:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO withdraws (user_id, amount, wallet_info) VALUES (?,?,?)",
            (user_id, amount, wallet_info)
        )
        # Balansdan ayiramiz
        conn.execute("UPDATE users SET balance = balance - ? WHERE user_id = ?", (amount, user_id))
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()

def get_pending_withdraws():
    conn = get_db()
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT w.*, u.full_name, u.username
            FROM withdraws w
            LEFT JOIN users u ON w.user_id = u.user_id
            WHERE w.status = 'pending'
            ORDER BY w.created_at ASC
        """)
        return cur.fetchall()
    finally:
        conn.close()

def resolve_withdraw(withdraw_id: int, status: str):
    conn = get_db()
    try:
        now_str = datetime.datetime.now().isoformat()
        if status == "rejected":
            cur = conn.cursor()
            cur.execute("SELECT user_id, amount FROM withdraws WHERE id = ?", (withdraw_id,))
            row = cur.fetchone()
            if row:
                conn.execute(
                    "UPDATE users SET balance = balance + ? WHERE user_id = ?",
                    (row["amount"], row["user_id"])
                )
        conn.execute(
            "UPDATE withdraws SET status = ?, resolved_at = ? WHERE id = ?",
            (status, now_str, withdraw_id)
        )
        conn.commit()
    finally:
        conn.close()

def get_withdraw_by_id(withdraw_id: int):
    conn = get_db()
    try:
        cur = conn.cursor()
        cur.execute("SELECT * FROM withdraws WHERE id = ?", (withdraw_id,))
        return cur.fetchone()
    finally:
        conn.close()

# ============================================================
#  🎨 KLAVIATURALAR
# ============================================================

def main_keyboard():
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    kb.add(
        types.KeyboardButton("💰 Balansim"),
        types.KeyboardButton("👤 Profilim"),
        types.KeyboardButton("🎁 Kunlik bonus"),
        types.KeyboardButton("👥 Referallarim"),
        types.KeyboardButton("🏆 Top referallar"),
        types.KeyboardButton("💸 Pul yechish"),
    )
    return kb

def admin_keyboard():
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    kb.add(
        types.KeyboardButton("📊 Statistika"),
        types.KeyboardButton("📢 Xabar yuborish"),
        types.KeyboardButton("👥 Foydalanuvchilar"),
        types.KeyboardButton("💳 Yechish so'rovlari"),
        types.KeyboardButton("➕ Kanal qo'shish"),
        types.KeyboardButton("➖ Kanal o'chirish"),
        types.KeyboardButton("💰 Coin qo'shish"),
        types.KeyboardButton("💰 Coin ayirish"),
        types.KeyboardButton("🏠 Asosiy menyu"),
    )
    return kb

def subscribe_keyboard(channels):
    kb = types.InlineKeyboardMarkup()
    for ch in channels:
        kb.add(types.InlineKeyboardButton(
            f"📢 {ch['channel_name']}",
            url=ch["invite_link"]
        ))
    kb.add(types.InlineKeyboardButton("✅ A'zo bo'ldim, tekshir", callback_data="check_sub"))
    return kb

def withdraw_confirm_keyboard(withdraw_id: int):
    kb = types.InlineKeyboardMarkup(row_width=2)
    kb.add(
        types.InlineKeyboardButton("✅ Tasdiqlash", callback_data=f"wd_approve_{withdraw_id}"),
        types.InlineKeyboardButton("❌ Rad etish", callback_data=f"wd_reject_{withdraw_id}")
    )
    return kb

# ============================================================
#  🔐 DEKORATORLAR
# ============================================================

def subscription_required(func):
    """Majburiy obuna tekshiruvi."""
    def wrapper(message):
        not_sub = check_subscription(message.from_user.id)
        if not_sub:
            bot.send_message(
                message.chat.id,
                "⛔️ <b>Botdan foydalanish uchun quyidagi kanallarga a'zo bo'ling:</b>",
                reply_markup=subscribe_keyboard(not_sub)
            )
            return
        func(message)
    return wrapper

def admin_required(func):
    """Admin tekshiruvi."""
    def wrapper(message):
        if message.from_user.id not in ADMIN_IDS:
            bot.send_message(message.chat.id, "⛔️ Siz admin emassiz!")
            return
        func(message)
    return wrapper

# ============================================================
#  🚀 /START
# ============================================================

@bot.message_handler(commands=["start"])
def cmd_start(message):
    user = message.from_user
    args = message.text.split()
    referrer_id = None

    if len(args) > 1:
        try:
            ref = int(args[1])
            if ref != user.id:
                referrer_id = ref
        except:
            pass

    is_new = register_user(
        user_id=user.id,
        username=user.username or "",
        full_name=user.full_name,
        referrer_id=referrer_id
    )

    # Kanallarni tekshir
    not_sub = check_subscription(user.id)
    if not_sub:
        bot.send_message(
            message.chat.id,
            f"👋 Salom, <b>{user.full_name}</b>!\n\n"
            "⛔️ Botdan foydalanish uchun quyidagi kanallarga a'zo bo'ling:",
            reply_markup=subscribe_keyboard(not_sub)
        )
        return

    welcome = (
        f"🌟 <b>UZCoin botiga xush kelibsiz!</b>\n\n"
        f"👤 Ism: <b>{user.full_name}</b>\n"
        f"💰 Balans: <b>{get_balance(user.id):.1f} UZCoin</b>\n\n"
        f"{'🎉 Referal orqali keldingiz! Referga +5 UZCoin berildi.' if is_new and referrer_id else ''}\n\n"
        f"📌 Menyu orqali barcha imkoniyatlardan foydalaning:"
    )

    bot.send_message(message.chat.id, welcome, reply_markup=main_keyboard())

# ============================================================
#  ✅ CALLBACK — Obuna tekshiruvi
# ============================================================

@bot.callback_query_handler(func=lambda c: c.data == "check_sub")
def callback_check_sub(call):
    not_sub = check_subscription(call.from_user.id)
    if not_sub:
        bot.answer_callback_query(
            call.id,
            "❌ Hali ham barcha kanallarga a'zo emassiz!",
            show_alert=True
        )
    else:
        bot.answer_callback_query(call.id, "✅ Rahmat! Endi botdan foydalanishingiz mumkin.")
        bot.delete_message(call.message.chat.id, call.message.message_id)
        bot.send_message(
            call.message.chat.id,
            f"✅ <b>A'zolik tasdiqlandi!</b>\n\n"
            f"🌟 UZCoin botiga xush kelibsiz!\n"
            f"💰 Balansiz: <b>{get_balance(call.from_user.id):.1f} UZCoin</b>",
            reply_markup=main_keyboard()
        )

# ============================================================
#  💰 BALANS
# ============================================================

@bot.message_handler(func=lambda m: m.text == "💰 Balansim")
@subscription_required
def btn_balance(message):
    bal = get_balance(message.from_user.id)
    bot.send_message(
        message.chat.id,
        f"💰 <b>Sizning balansingiz</b>\n\n"
        f"🪙 <b>{bal:.1f} UZCoin</b>\n\n"
        f"💸 Minimal yechish: <b>{MIN_WITHDRAW} UZCoin</b>",
        reply_markup=main_keyboard()
    )

# ============================================================
#  👤 PROFIL
# ============================================================

@bot.message_handler(func=lambda m: m.text == "👤 Profilim")
@subscription_required
def btn_profile(message):
    user = get_user(message.from_user.id)
    ref_count = get_referral_count(message.from_user.id)
    ref_link = f"https://t.me/{BOT_USERNAME}?start={message.from_user.id}"

    text = (
        f"👤 <b>Profilingiz</b>\n\n"
        f"🆔 ID: <code>{message.from_user.id}</code>\n"
        f"📛 Ism: <b>{user['full_name']}</b>\n"
        f"💰 Balans: <b>{user['balance']:.1f} UZCoin</b>\n"
        f"👥 Referallar: <b>{ref_count} ta</b>\n"
        f"📅 Ro'yxatdan o'tgan: <b>{user['joined_at'][:10]}</b>\n\n"
        f"🔗 <b>Referal linkingiz:</b>\n"
        f"<code>{ref_link}</code>"
    )
    bot.send_message(message.chat.id, text, reply_markup=main_keyboard())

# ============================================================
#  🎁 KUNLIK BONUS
# ============================================================

@bot.message_handler(func=lambda m: m.text == "🎁 Kunlik bonus")
@subscription_required
def btn_daily_bonus(message):
    if can_claim_bonus(message.from_user.id):
        claim_bonus(message.from_user.id)
        bal = get_balance(message.from_user.id)
        bot.send_message(
            message.chat.id,
            f"🎁 <b>Kunlik bonus olindi!</b>\n\n"
            f"✅ +{DAILY_BONUS_AMOUNT} UZCoin hisobingizga qo'shildi!\n"
            f"💰 Yangi balansiz: <b>{bal:.1f} UZCoin</b>\n\n"
            f"⏳ Keyingi bonus: <b>24 soatdan so'ng</b>",
            reply_markup=main_keyboard()
        )
    else:
        nxt = next_bonus_time(message.from_user.id)
        bot.send_message(
            message.chat.id,
            f"⏳ <b>Bonus allaqachon olindi!</b>\n\n"
            f"🕐 Keyingi bonusgacha: <b>{nxt}</b>",
            reply_markup=main_keyboard()
        )

# ============================================================
#  👥 REFERALLAR
# ============================================================

@bot.message_handler(func=lambda m: m.text == "👥 Referallarim")
@subscription_required
def btn_referrals(message):
    ref_count = get_referral_count(message.from_user.id)
    ref_link = f"https://t.me/{BOT_USERNAME}?start={message.from_user.id}"
    earned = ref_count * REFERRAL_BONUS

    bot.send_message(
        message.chat.id,
        f"👥 <b>Referal tizimi</b>\n\n"
        f"🔗 Linkingiz:\n<code>{ref_link}</code>\n\n"
        f"👤 Taklif qilganlar: <b>{ref_count} ta</b>\n"
        f"💰 Jami daromad: <b>{earned:.1f} UZCoin</b>\n\n"
        f"💡 Har bir yangi foydalanuvchi uchun <b>+{REFERRAL_BONUS} UZCoin</b> olasiz!",
        reply_markup=main_keyboard()
    )

# ============================================================
#  🏆 TOP REFERALLAR
# ============================================================

@bot.message_handler(func=lambda m: m.text == "🏆 Top referallar")
@subscription_required
def btn_top_referrers(message):
    top = get_top_referrers(10)
    medals = ["🥇", "🥈", "🥉"] + ["🏅"] * 7

    lines = ["🏆 <b>Top 10 Referal Reytingi</b>\n"]
    for i, row in enumerate(top):
        name = row["full_name"] or "Noma'lum"
        count = row["ref_count"]
        medal = medals[i] if i < len(medals) else "▪️"
        you = " 👈 <b>Siz</b>" if row["user_id"] == message.from_user.id else ""
        lines.append(f"{medal} {i+1}. {name} — <b>{count} ta</b>{you}")

    if not top or top[0]["ref_count"] == 0:
        lines.append("\n📭 Hali referal yo'q.")

    bot.send_message(message.chat.id, "\n".join(lines), reply_markup=main_keyboard())

# ============================================================
#  💸 PUL YECHISH
# ============================================================

user_states = {}  # {user_id: state}
user_temp = {}    # {user_id: temp_data}

@bot.message_handler(func=lambda m: m.text == "💸 Pul yechish")
@subscription_required
def btn_withdraw(message):
    bal = get_balance(message.from_user.id)
    if bal < MIN_WITHDRAW:
        bot.send_message(
            message.chat.id,
            f"❌ <b>Balansingiz yetarli emas!</b>\n\n"
            f"💰 Sizning balansingiz: <b>{bal:.1f} UZCoin</b>\n"
            f"💸 Minimal yechish: <b>{MIN_WITHDRAW} UZCoin</b>",
            reply_markup=main_keyboard()
        )
        return

    user_states[message.from_user.id] = "withdraw_amount"
    user_temp[message.from_user.id] = {}

    kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
    kb.add(types.KeyboardButton("❌ Bekor qilish"))

    bot.send_message(
        message.chat.id,
        f"💸 <b>Pul yechish</b>\n\n"
        f"💰 Sizning balansingiz: <b>{bal:.1f} UZCoin</b>\n"
        f"💸 Minimal miqdor: <b>{MIN_WITHDRAW} UZCoin</b>\n\n"
        f"📝 Qancha UZCoin yechmoqchisiz? (son kiriting):",
        reply_markup=kb
    )

# ============================================================
#  📝 MATN XABARLARI — state machine
# ============================================================

@bot.message_handler(func=lambda m: m.from_user.id in user_states)
def handle_state(message):
    uid = message.from_user.id
    state = user_states.get(uid)

    # Bekor qilish
    if message.text == "❌ Bekor qilish":
        user_states.pop(uid, None)
        user_temp.pop(uid, None)
        bot.send_message(message.chat.id, "❌ Bekor qilindi.", reply_markup=main_keyboard())
        return

    # Admin states
    if state == "admin_broadcast":
        text = message.text
        user_states.pop(uid, None)
        ids = get_all_user_ids()
        success = 0
        for target_id in ids:
            try:
                bot.send_message(target_id, f"📢 <b>Admin xabari:</b>\n\n{text}")
                success += 1
                time.sleep(0.05)
            except:
                pass
        bot.send_message(
            message.chat.id,
            f"✅ Xabar yuborildi!\n👥 Muvaffaqiyatli: {success}/{len(ids)} ta",
            reply_markup=admin_keyboard()
        )
        return

    if state == "admin_add_coin_id":
        try:
            target_id = int(message.text.strip())
            user_temp[uid]["target_id"] = target_id
            user_states[uid] = "admin_add_coin_amount"
            bot.send_message(message.chat.id, "💰 Qancha UZCoin qo'shish kerak?")
        except:
            bot.send_message(message.chat.id, "❌ Noto'g'ri ID! Qayta kiriting:")
        return

    if state == "admin_add_coin_amount":
        try:
            amount = float(message.text.strip())
            target_id = user_temp[uid]["target_id"]
            user = get_user(target_id)
            if not user:
                bot.send_message(message.chat.id, "❌ Foydalanuvchi topilmadi!", reply_markup=admin_keyboard())
            else:
                add_balance(target_id, amount)
                try:
                    bot.send_message(target_id, f"🎉 Hisobingizga <b>+{amount:.1f} UZCoin</b> qo'shildi!")
                except:
                    pass
                bot.send_message(
                    message.chat.id,
                    f"✅ {user['full_name']} ga <b>+{amount:.1f} UZCoin</b> qo'shildi!",
                    reply_markup=admin_keyboard()
                )
            user_states.pop(uid, None)
            user_temp.pop(uid, None)
        except:
            bot.send_message(message.chat.id, "❌ Noto'g'ri miqdor! Qayta kiriting:")
        return

    if state == "admin_remove_coin_id":
        try:
            target_id = int(message.text.strip())
            user_temp[uid]["target_id"] = target_id
            user_states[uid] = "admin_remove_coin_amount"
            bot.send_message(message.chat.id, "💰 Qancha UZCoin ayirish kerak?")
        except:
            bot.send_message(message.chat.id, "❌ Noto'g'ri ID! Qayta kiriting:")
        return

    if state == "admin_remove_coin_amount":
        try:
            amount = float(message.text.strip())
            target_id = user_temp[uid]["target_id"]
            user = get_user(target_id)
            if not user:
                bot.send_message(message.chat.id, "❌ Foydalanuvchi topilmadi!", reply_markup=admin_keyboard())
            else:
                new_bal = max(0, user["balance"] - amount)
                set_balance(target_id, new_bal)
                try:
                    bot.send_message(target_id, f"⚠️ Hisobingizdan <b>{amount:.1f} UZCoin</b> ayirildi!")
                except:
                    pass
                bot.send_message(
                    message.chat.id,
                    f"✅ {user['full_name']} dan <b>{amount:.1f} UZCoin</b> ayirildi!\n"
                    f"Yangi balans: <b>{new_bal:.1f} UZCoin</b>",
                    reply_markup=admin_keyboard()
                )
            user_states.pop(uid, None)
            user_temp.pop(uid, None)
        except:
            bot.send_message(message.chat.id, "❌ Noto'g'ri miqdor! Qayta kiriting:")
        return

    if state == "admin_add_channel":
        parts = message.text.strip().split("|")
        if len(parts) != 3:
            bot.send_message(
                message.chat.id,
                "❌ Format noto'g'ri!\n\nQuyidagi formatda yuboring:\n"
                "<code>kanal_id|Kanal nomi|https://t.me/...</code>\n\n"
                "Masalan: <code>-1001234567890|My Channel|https://t.me/mychannel</code>"
            )
            return
        ch_id, ch_name, ch_link = [p.strip() for p in parts]
        ok = add_channel(ch_id, ch_name, ch_link)
        user_states.pop(uid, None)
        if ok:
            bot.send_message(message.chat.id, f"✅ <b>{ch_name}</b> kanali qo'shildi!", reply_markup=admin_keyboard())
        else:
            bot.send_message(message.chat.id, "❌ Bu kanal allaqachon mavjud!", reply_markup=admin_keyboard())
        return

    if state == "admin_remove_channel":
        ch_id = message.text.strip()
        remove_channel(ch_id)
        user_states.pop(uid, None)
        bot.send_message(message.chat.id, f"✅ Kanal ({ch_id}) o'chirildi!", reply_markup=admin_keyboard())
        return

    # Withdraw states
    if state == "withdraw_amount":
        try:
            amount = float(message.text.strip())
            bal = get_balance(uid)
            if amount < MIN_WITHDRAW:
                bot.send_message(
                    message.chat.id,
                    f"❌ Minimal yechish miqdori: <b>{MIN_WITHDRAW} UZCoin</b>\n"
                    f"Siz kiritdingiz: <b>{amount:.1f}</b>"
                )
                return
            if amount > bal:
                bot.send_message(
                    message.chat.id,
                    f"❌ Balansingiz yetarli emas!\n"
                    f"💰 Sizning balansingiz: <b>{bal:.1f} UZCoin</b>"
                )
                return
            user_temp[uid]["amount"] = amount
            user_states[uid] = "withdraw_wallet"
            bot.send_message(
                message.chat.id,
                f"✅ Miqdor: <b>{amount:.1f} UZCoin</b>\n\n"
                f"💳 Endi karta yoki hamyon ma'lumotingizni kiriting\n"
                f"(Masalan: <code>8600 1234 5678 9012</code> yoki <code>+998901234567</code>):"
            )
        except:
            bot.send_message(message.chat.id, "❌ Noto'g'ri raqam! Faqat son kiriting:")
        return

    if state == "withdraw_wallet":
        wallet = message.text.strip()
        amount = user_temp[uid].get("amount", 0)
        user_states.pop(uid, None)
        user_temp.pop(uid, None)

        withdraw_id = create_withdraw(uid, amount, wallet)
        user = get_user(uid)

        # Adminlarga xabar
        for admin_id in ADMIN_IDS:
            try:
                bot.send_message(
                    admin_id,
                    f"💸 <b>Yangi yechish so'rovi #{withdraw_id}</b>\n\n"
                    f"👤 Foydalanuvchi: {user['full_name']} (<code>{uid}</code>)\n"
                    f"💰 Miqdor: <b>{amount:.1f} UZCoin</b>\n"
                    f"💳 Hamyon: <code>{wallet}</code>\n"
                    f"📅 Vaqt: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M')}",
                    reply_markup=withdraw_confirm_keyboard(withdraw_id)
                )
            except:
                pass

        bot.send_message(
            message.chat.id,
            f"✅ <b>Yechish so'rovi yuborildi!</b>\n\n"
            f"💰 Miqdor: <b>{amount:.1f} UZCoin</b>\n"
            f"💳 Hamyon: <code>{wallet}</code>\n\n"
            f"⏳ Admin tomonidan ko'rib chiqiladi.",
            reply_markup=main_keyboard()
        )
        return

# ============================================================
#  📊 ADMIN PANEL
# ============================================================

@bot.message_handler(commands=["admin"])
def cmd_admin(message):
    if message.from_user.id not in ADMIN_IDS:
        bot.send_message(message.chat.id, "⛔️ Siz admin emassiz!")
        return
    bot.send_message(
        message.chat.id,
        "🛠 <b>Admin paneli</b>\n\nKerakli bo'limni tanlang:",
        reply_markup=admin_keyboard()
    )

@bot.message_handler(func=lambda m: m.text == "📊 Statistika" and m.from_user.id in ADMIN_IDS)
def admin_stats(message):
    total = get_total_users()
    channels = get_channels()
    pending = get_pending_withdraws()
    conn = get_db()
    try:
        cur = conn.cursor()
        cur.execute("SELECT SUM(balance) FROM users")
        total_coins = cur.fetchone()[0] or 0
        cur.execute("SELECT COUNT(*) FROM referrals")
        total_refs = cur.fetchone()[0] or 0
    finally:
        conn.close()

    bot.send_message(
        message.chat.id,
        f"📊 <b>Bot statistikasi</b>\n\n"
        f"👥 Jami foydalanuvchilar: <b>{total} ta</b>\n"
        f"💰 Jami UZCoin: <b>{total_coins:.1f}</b>\n"
        f"👥 Jami referallar: <b>{total_refs} ta</b>\n"
        f"📢 Kanallar: <b>{len(channels)} ta</b>\n"
        f"💸 Kutayotgan so'rovlar: <b>{len(pending)} ta</b>",
        reply_markup=admin_keyboard()
    )

@bot.message_handler(func=lambda m: m.text == "👥 Foydalanuvchilar" and m.from_user.id in ADMIN_IDS)
def admin_users(message):
    conn = get_db()
    try:
        cur = conn.cursor()
        cur.execute("SELECT user_id, full_name, balance, joined_at FROM users ORDER BY joined_at DESC LIMIT 15")
        users = cur.fetchall()
    finally:
        conn.close()

    lines = [f"👥 <b>So'nggi 15 foydalanuvchi</b>\n"]
    for u in users:
        lines.append(
            f"• {u['full_name']} (<code>{u['user_id']}</code>) — "
            f"<b>{u['balance']:.1f} UZCoin</b>"
        )
    bot.send_message(message.chat.id, "\n".join(lines) or "📭 Foydalanuvchilar yo'q.", reply_markup=admin_keyboard())

@bot.message_handler(func=lambda m: m.text == "📢 Xabar yuborish" and m.from_user.id in ADMIN_IDS)
def admin_broadcast(message):
    user_states[message.from_user.id] = "admin_broadcast"
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
    kb.add(types.KeyboardButton("❌ Bekor qilish"))
    bot.send_message(
        message.chat.id,
        "📢 <b>Barcha foydalanuvchilarga xabar yuborish</b>\n\n"
        "Xabar matnini yuboring:",
        reply_markup=kb
    )

@bot.message_handler(func=lambda m: m.text == "💳 Yechish so'rovlari" and m.from_user.id in ADMIN_IDS)
def admin_withdraws(message):
    pending = get_pending_withdraws()
    if not pending:
        bot.send_message(message.chat.id, "📭 Kutayotgan yechish so'rovlari yo'q.", reply_markup=admin_keyboard())
        return
    for w in pending:
        bot.send_message(
            message.chat.id,
            f"💸 <b>Yechish so'rovi #{w['id']}</b>\n\n"
            f"👤 {w['full_name']} (<code>{w['user_id']}</code>)\n"
            f"💰 Miqdor: <b>{w['amount']:.1f} UZCoin</b>\n"
            f"💳 Hamyon: <code>{w['wallet_info']}</code>\n"
            f"📅 Vaqt: {w['created_at']}",
            reply_markup=withdraw_confirm_keyboard(w["id"])
        )

@bot.message_handler(func=lambda m: m.text == "💰 Coin qo'shish" and m.from_user.id in ADMIN_IDS)
def admin_add_coin(message):
    user_states[message.from_user.id] = "admin_add_coin_id"
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
    kb.add(types.KeyboardButton("❌ Bekor qilish"))
    bot.send_message(message.chat.id, "👤 Foydalanuvchi ID-sini kiriting:", reply_markup=kb)

@bot.message_handler(func=lambda m: m.text == "💰 Coin ayirish" and m.from_user.id in ADMIN_IDS)
def admin_remove_coin(message):
    user_states[message.from_user.id] = "admin_remove_coin_id"
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
    kb.add(types.KeyboardButton("❌ Bekor qilish"))
    bot.send_message(message.chat.id, "👤 Foydalanuvchi ID-sini kiriting:", reply_markup=kb)

@bot.message_handler(func=lambda m: m.text == "➕ Kanal qo'shish" and m.from_user.id in ADMIN_IDS)
def admin_add_channel(message):
    user_states[message.from_user.id] = "admin_add_channel"
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
    kb.add(types.KeyboardButton("❌ Bekor qilish"))
    bot.send_message(
        message.chat.id,
        "📢 <b>Kanal qo'shish</b>\n\n"
        "Quyidagi formatda yuboring:\n"
        "<code>kanal_id|Kanal nomi|https://t.me/invite_link</code>\n\n"
        "<b>Misol:</b>\n"
        "<code>-1001234567890|Mening kanalim|https://t.me/mychannel</code>\n\n"
        "💡 Kanal ID-ni bilish uchun @username_to_id_bot dan foydalaning.",
        reply_markup=kb
    )

@bot.message_handler(func=lambda m: m.text == "➖ Kanal o'chirish" and m.from_user.id in ADMIN_IDS)
def admin_remove_channel(message):
    channels = get_channels()
    if not channels:
        bot.send_message(message.chat.id, "📭 Hech qanday kanal yo'q.", reply_markup=admin_keyboard())
        return
    user_states[message.from_user.id] = "admin_remove_channel"
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
    kb.add(types.KeyboardButton("❌ Bekor qilish"))
    lines = ["📋 <b>Mavjud kanallar:</b>\n"]
    for ch in channels:
        lines.append(f"• <b>{ch['channel_name']}</b> — ID: <code>{ch['channel_id']}</code>")
    lines.append("\n👇 O'chirmoqchi bo'lgan kanal ID-sini yuboring:")
    bot.send_message(message.chat.id, "\n".join(lines), reply_markup=kb)

@bot.message_handler(func=lambda m: m.text == "🏠 Asosiy menyu" and m.from_user.id in ADMIN_IDS)
def admin_main_menu(message):
    bot.send_message(message.chat.id, "🏠 Asosiy menyu:", reply_markup=main_keyboard())

# ============================================================
#  ✅ WITHDRAW CALLBACK
# ============================================================

@bot.callback_query_handler(func=lambda c: c.data.startswith("wd_"))
def callback_withdraw(call):
    if call.from_user.id not in ADMIN_IDS:
        bot.answer_callback_query(call.id, "⛔️ Ruxsat yo'q!")
        return

    parts = call.data.split("_")
    action = parts[1]
    withdraw_id = int(parts[2])

    w = get_withdraw_by_id(withdraw_id)
    if not w:
        bot.answer_callback_query(call.id, "❌ So'rov topilmadi!")
        return
    if w["status"] != "pending":
        bot.answer_callback_query(call.id, f"⚠️ Bu so'rov allaqachon {w['status']}!", show_alert=True)
        return

    if action == "approve":
        resolve_withdraw(withdraw_id, "approved")
        try:
            bot.send_message(
                w["user_id"],
                f"✅ <b>Yechish so'rovingiz tasdiqlandi!</b>\n\n"
                f"💰 Miqdor: <b>{w['amount']:.1f} UZCoin</b>\n"
                f"💳 Hamyon: <code>{w['wallet_info']}</code>\n\n"
                f"Tez orada hisobingizga o'tkaziladi."
            )
        except:
            pass
        bot.answer_callback_query(call.id, "✅ Tasdiqlandi!")
        bot.edit_message_text(
            f"✅ <b>Tasdiqlangan — #{withdraw_id}</b>\n"
            f"💰 {w['amount']:.1f} UZCoin | 💳 {w['wallet_info']}",
            call.message.chat.id, call.message.message_id
        )

    elif action == "reject":
        resolve_withdraw(withdraw_id, "rejected")
        try:
            bot.send_message(
                w["user_id"],
                f"❌ <b>Yechish so'rovingiz rad etildi!</b>\n\n"
                f"💰 <b>{w['amount']:.1f} UZCoin</b> hisobingizga qaytarildi."
            )
        except:
            pass
        bot.answer_callback_query(call.id, "❌ Rad etildi!")
        bot.edit_message_text(
            f"❌ <b>Rad etilgan — #{withdraw_id}</b>\n"
            f"💰 {w['amount']:.1f} UZCoin | 💳 {w['wallet_info']}",
            call.message.chat.id, call.message.message_id
        )

# ============================================================
#  ❓ NOMA'LUM BUYRUQ
# ============================================================

@bot.message_handler(func=lambda m: True)
def handle_unknown(message):
    if message.from_user.id in user_states:
        handle_state(message)
        return
    not_sub = check_subscription(message.from_user.id)
    if not_sub:
        bot.send_message(
            message.chat.id,
            "⛔️ Botdan foydalanish uchun kanallarga a'zo bo'ling:",
            reply_markup=subscribe_keyboard(not_sub)
        )
        return
    bot.send_message(message.chat.id, "📌 Menyu tugmalaridan foydalaning:", reply_markup=main_keyboard())

# ============================================================
#  🚀 ISHGA TUSHIRISH
# ============================================================

if __name__ == "__main__":
    print("=" * 50)
    print("🤖 UZCoin Bot ishga tushmoqda...")
    print(f"📦 Baza: {DB_PATH}")
    print(f"👑 Adminlar: {ADMIN_IDS}")
    print("=" * 50)

    while True:
        try:
            bot.infinity_polling(timeout=60, long_polling_timeout=60)
        except Exception as e:
            print(f"[XATO] {e}")
            time.sleep(5)
            print("🔄 Qayta urinish...")
