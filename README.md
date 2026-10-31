# 📊 DXnumbers Bot

> **Telegram Bot** — Firebase Realtime Sync সহ একটি পূর্ণাঙ্গ Telegram বট, Force Join Channel, Refer & Withdrawal এবং Support Link সহ।

---

## ✨ Features

| Feature | Description |
|---------|-------------|
| 🔗 **Force Join Channel** | চ্যানেলে জয়েন না করলে বট ব্যবহার করা যাবে না |
| 💬 **Support Link** | ইউজারদের জন্য support link |
| 💰 **Refer & Earn** | রেফারেল সিস্টেম সহ ব্যালেন্স |
| 💳 **Withdrawal System** | bKash / Nagad ইত্যাদির মাধ্যমে উইথড্র |
| 🔥 **Firebase Sync** | সব ডেটা Firebase Firestore এ real-time sync |
| 📢 **Broadcast** | সব ইউজারকে একসাথে message পাঠানো |
| 🏆 **Leader Board** | Top referrers ও withdrawal history |
| 🏆 **Leader Board** | Top referrers ও withdrawal history |

---

## 🚀 Quick Setup

### 1️⃣ Repository Clone করুন

```bash
git clone https://github.com/YOUR_USERNAME/DXnumbers-bot.git
cd DXnumbers-bot
```

### 2️⃣ Dependencies Install করুন

```bash
pip install -r requirements.txt
```

### 3️⃣ `.env` ফাইল তৈরি করুন

```bash
cp .env.example .env
```

এরপর `.env` ফাইলটি edit করুন এবং আপনার নিজের values দিন:

```env
# Telegram Bot Token (@BotFather থেকে নিন)
BOT_TOKEN=1234567890:ABCdefGhIJKlmNoPQRsTUVwxYZ

# আপনার Telegram User ID (@userinfobot থেকে নিন)
OWNER_ID=987654321

# Force Join Channel (চালু করতে true করুন)
FORCE_JOIN_ON=true
FORCE_JOIN_CHANNELS=@your_channel,@another_channel

# Support Link
SUPPORT_LINK=https://t.me/your_support_group
```

### 4️⃣ Firebase Credentials সেট করুন

1. [Firebase Console](https://console.firebase.google.com/) → আপনার Project → Project Settings
2. **Service Accounts** → **Generate new private key**
3. Downloaded JSON ফাইলটি project folder এ রাখুন এবং নাম দিন: `firebase_credentials.json`

> ⚠️ `firebase_credentials.json` কখনো GitHub এ push করবেন না — এটি `.gitignore` এ আছে।

অথবা template ব্যবহার করুন:
```bash
cp firebase_credentials.template.json firebase_credentials.json
# এরপর ফাইলটি edit করে আপনার real values দিন
```

### 5️⃣ বট চালু করুন

```bash
python bot.py
```

---

## ⚙️ সম্পূর্ণ `.env` Configuration

```env
# ─── TELEGRAM BOT ──────────────────────────────────────────
BOT_TOKEN=YOUR_TELEGRAM_BOT_TOKEN
OWNER_ID=123456789

# ─── FIREBASE ──────────────────────────────────────────────
FIREBASE_CREDENTIALS_PATH=firebase_credentials.json

# ─── FORCE JOIN CHANNEL ────────────────────────────────────
# true = Force Join চালু, false = বন্ধ
FORCE_JOIN_ON=false

# Channel username বা numeric ID (comma দিয়ে multiple)
# উদাহরণ: @mychannel  অথবা  -1001234567890
FORCE_JOIN_CHANNELS=@chan1,@chan2

# ─── SUPPORT LINK ──────────────────────────────────────────
SUPPORT_LINK=https://t.me/your_support

# ─── WITHDRAWAL ────────────────────────────────────────────
WITHDRAWAL_GROUP=-1009876543210
WITHDRAW_ON=true
MIN_WITHDRAW=30.0

# ─── REWARDS ───────────────────────────────────────────────
REFER_REWARD=0.2
COOLDOWN=10
```

---

## 🔧 Admin Panel থেকে সবকিছু Manual Change করা যাবে

> ✅ **`.env` শুধু প্রথমবারের default।** বট চালু হওয়ার পর **Admin Panel থেকে সবকিছু manually change করা যাবে** এবং সেই পরিবর্তন Firebase এ save হয়ে চিরস্থায়ী থাকবে।  
> Bot restart করলেও admin এর করা changes হারাবে না।

---

### কীভাবে কাজ করে:

```
Bot Start
  ↓
.env থেকে initial defaults লোড হয়
  ↓
Firebase / local DB থেকে load_db() call হয়
  ↓
Firebase এ যা আছে তা .env-কে override করে ✅
  ↓
Admin Panel থেকে যেকোনো change → Firebase এ save
  ↓
পরের restart এও সেই changes থাকে ✅
```

---

### 🔗 Force Join Channel:
- **Admin Panel** → **System Settings** → **Force Join**
- ✅ Channel add / remove করুন
- ✅ ON / OFF toggle করুন
- ✅ Private channel এর numeric ID (-100...) দিন

### 💬 Support Link:
- **Admin Panel** → **System Settings** → **DXA Control**
- ✅ **Support Link** edit করুন
- ✅ **Withdrawal Group** set করুন

### ⚙️ System Settings (সব):
- **Admin Panel** → **System Settings**
- ✅ Min Withdraw পরিবর্তন
- ✅ Refer Reward
- ✅ Cooldown
- ✅ Withdrawal ON/OFF
- ✅ Withdrawal Methods (bKash, Nagad, ইত্যাদি)

### 👥 User Management:
- ✅ User balance add/remove
- ✅ User ban/unban
- ✅ Admin add/remove
- ✅ সব user কে broadcast

---

## 📁 Project Structure

```
DXnumbers-bot/
├── bot.py                          # 🤖 Main bot file
├── requirements.txt                # 📦 Python dependencies
├── .env                            # 🔐 Your secrets (gitignored)
├── .env.example                    # 📋 Config template
├── firebase_credentials.json       # 🔥 Firebase key (gitignored)
├── firebase_credentials.template.json  # 📄 Firebase template
├── bot_data.json                   # 💾 Local DB cache (gitignored)
├── users.json                      # 👥 User list cache (gitignored)
├── .gitignore                      # 🚫 Files to ignore
└── README.md                       # 📖 This file
```

---

## 🛠 Deployment (Server এ চালানো)

### Screen ব্যবহার করে (Linux VPS):
```bash
screen -S dxbot
python bot.py
# Ctrl+A তারপর D চাপলে detach হবে
```

### PM2 ব্যবহার করে:
```bash
pip install pm2  # বা npm install -g pm2
pm2 start bot.py --name dxbot --interpreter python3
pm2 save
pm2 startup
```

### systemd service:
```ini
# /etc/systemd/system/dxbot.service
[Unit]
Description=DXnumbers Telegram Bot
After=network.target

[Service]
User=YOUR_USER
WorkingDirectory=/path/to/DXnumbers-bot
ExecStart=/usr/bin/python3 /path/to/DXnumbers-bot/bot.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```
```bash
sudo systemctl enable dxbot
sudo systemctl start dxbot
```

---

## 🔐 Security Notes

- ✅ কখনো `BOT_TOKEN` বা Firebase credentials GitHub এ push করবেন না
- ✅ `.env` এবং `firebase_credentials.json` সবসময় `.gitignore` এ রাখুন
- ✅ Repository private রাখুন যদি public করতে না চান
- ✅ Firebase Firestore rules properly set করুন

---

## 📞 Requirements

- Python 3.8+
- Firebase Project (Firestore Database)
- Telegram Bot Token

---

## 📄 License

এই bot টি private use এর জন্য। Commercial use এর আগে অনুমতি নিন।
