# 🧩 DXnumbers Bot — নতুন ফিচার যোগ করার সম্পূর্ণ গাইড (A to Z)

> এই গাইডটি পড়লে আপনি নিজেই **ইউজার মেনু** এবং **অ্যাডমিন প্যানেলে** যেকোনো নতুন ফিচার যোগ করতে পারবেন — কোন কোড কোথায় বসাতে হবে, সব সুনির্দিষ্ট জায়গা সহ।
>
> কোডের ভেতরেও প্রতিটি জায়গা **ZONE** নামে চিহ্নিত করা আছে। কোডে `Ctrl+F` করে `ZONE-A`, `ZONE-B`... লিখে সরাসরি জায়গায় পৌঁছাতে পারবেন।

---

## 📖 ১. বটের কোড ম্যাপ — কোন ফাংশন কী কাজ করে

| # | ফাংশন / অংশ | কী কাজ করে | আপনার জন্য |
|---|---|---|---|
| ১ | `main_menu(user_id)` | ইউজার/অ্যাডমিনের **রিপ্লাই কিবোর্ড** বানায় (Refer, WITHDRAWAL, SUPPORT, Admin Panel) | 🧩 **ZONE-A / ZONE-A2** |
| ২ | `admin_panel_keyboard()` | অ্যাডমিন প্যানেলের **ইনলাইন বাটন** (Leader Board, Broadcast, System) | 🧩 **ZONE-D** |
| ৩ | `system_settings_keyboard()` | System Settings এর ইনলাইন বাটন (Force Join, Admin Mgmt, User Mgmt, DXA Control...) | 🧩 **ZONE-D2** |
| ৪ | `handle_message(msg)` | ইউজার/অ্যাডমিন **যা টাইপ করে** বা কিবোর্ড বাটন চাপে তা প্রসেস করে | 🧩 **ZONE-B / ZONE-C** |
| ৫ | `handle_callback(call)` | সব **ইনলাইন বাটনের** চাপ প্রসেস করে | 🧩 **ZONE-E** |
| ৬ | `bot_settings` + `FS_KEYS` | সব সেটিংস এখানে সেভ হয় (Firestore + local JSON) | নতুন সেটিংস লাগলে এখানে |
| ৭ | `user_states` / `temp_data` | ইনপুট নেওয়ার সময় অবস্থা মনে রাখে | ইনপুট-ফিচারে লাগবে |

---

## 📐 ২. নতুন ফিচার বানানোর ৪-ধাপ রেসিপি (সব ফিচারে একই নিয়ম)

```
ধাপ-১: বাটন বানান        → কোন মেনুতে দেখাবে সেই keyboard ফাংশনে (ZONE-A বা ZONE-D/D2)
ধাপ-২: কাজ বসান          → বাটন চাপলে কী হবে:
                            • কিবোর্ড বাটন (text)   → ZONE-B  (handle_message)
                            • ইনলাইন বাটন (callback) → ZONE-E  (handle_callback)
ধাপ-৩: ইনপুট লাগলে       → user_states সেট করুন, লেখা ধরুন ZONE-C তে
ধাপ-৪: সেটিংস বদলালে     → save_db() কল করুন (না দিলে রিস্টার্টে হারিয়ে যাবে)
```

**ফিচারের ধরন অনুযায়ী কোন জোন লাগবে:**

| ফিচারের ধরন | বাটন কোথায় | কাজ কোথায় | ইনপুট কোথায় |
|---|---|---|---|
| ইউজার — শুধু তথ্য দেখায় | ZONE-A | ZONE-B | লাগবে না |
| ইউজার — লেখা নেয় (যেমন ফর্ম) | ZONE-A | ZONE-B (স্টেট সেট) | ZONE-C |
| অ্যাডমিন — প্যানেলে স্ক্রিন | ZONE-D | ZONE-E | লাগবে না |
| অ্যাডমিন — সেটিংস বদলায় (ইনপুট) | ZONE-D বা D2 | ZONE-E (স্টেট সেট) | ZONE-C |
| অ্যাডমিন — কিবোর্ড বাটন | ZONE-A2 | ZONE-B | প্রয়োজনে ZONE-C |

---

## 🗺️ ৩. ZONE রেফারেন্স — সুনির্দিষ্ট জায়গা (৭টি জোন)

### 🧩 ZONE-A — ইউজার মেনুর বাটন (রিপ্লাই কিবোর্ড)
- **কোথায়:** `def main_menu(user_id):` ফাংশনের ভেতরে (`Ctrl+F` → `ZONE-A`)
- **কী বসাবেন:** নতুন ইউজার বাটনের জন্য `kb.append(...)` লাইন
- **সাথে অবশ্যই:** বাটনের নাম উপরের `USER_MENU_BUTTONS = ["Refer", "WITHDRAWAL", "SUPPORT"]` লিস্টেও যোগ করুন

```python
# main_menu() এর ভেতরে:
kb.append([{"text": "👤 MY ACCOUNT", "style": "primary"}])
# এবং উপরে:
USER_MENU_BUTTONS = ["Refer", "WITHDRAWAL", "SUPPORT", "👤 MY ACCOUNT"]
```

### 🧩 ZONE-A2 — শুধু অ্যাডমিনের কিবোর্ড বাটন
- **কোথায়:** `main_menu()` এর ভেতরে `if is_admin(user_id):` ব্লকে
- **কাজ কোথায়:** ZONE-B তে `elif text == "বাটন" and is_admin(chat_id):`

### 🧩 ZONE-B — ইউজার কিবোর্ড বাটনের "কাজ"
- **কোথায়:** `handle_message()` ফাংশনের **একদম শেষে** (SUPPORT ব্লকের পরে, `Ctrl+F` → `ZONE-B`)
- **নিয়ম:** `elif text == "বাটনের নাম":` — নাম হুবহু একই হতে হবে

### 🧩 ZONE-C — ইনপুট (টাইপ করা লেখা) ধরার জায়গা
- **কোথায়:** `handle_message()` এর স্টেট-চেইনের শেষে (`wait_for_withdraw_number` ব্লকের পরে, `Ctrl+F` → `ZONE-C`)
- **নিয়ম:** `elif state == "wait_for_xxx" and text:` — শেষে `del user_states/temp_data` + `return` বাধ্যতামূলক

### 🧩 ZONE-D — অ্যাডমিন প্যানেলের নতুন বাটন
- **কোথায়:** `admin_panel_keyboard()` ফাংশনে (Close বাটনের ঠিক উপরে, `Ctrl+F` → `ZONE-D`)
- **নিয়ম:** `callback_data` ইউনিক দিন (যেমন `adm_xxx`), কাজ বসান ZONE-E তে

### 🧩 ZONE-D2 — System Settings এ নতুন বাটন
- **কোথায়:** `system_settings_keyboard()` ফাংশনে (Back বাটনের ঠিক উপরে, `Ctrl+F` → `ZONE-D2`)
- **নিয়ম:** `callback_data` তে `ss_xxx` নামক কনভেনশন ব্যবহার করুন

### 🧩 ZONE-E — ইনলাইন বাটনের "কাজ"
- **কোথায়:** `handle_callback()` ফাংশনের **একদম শেষে** (`Ctrl+F` → `ZONE-E`)
- **নিয়ম-১:** নতুন `elif` সবসময় শেষে যোগ করুন
- **নিয়ম-২:** নির্দিষ্ট ম্যাচ (`data == "adm_x"`) আগে, prefix ম্যাচ (`data.startswith("x_")`) পরে রাখুন
- **নিয়ম-৩:** অ্যাডমিন-অনলি হলে শুরুতে `is_admin()` চেক দিন

---

## 💻 ৪. কপি-পেস্ট টেমপ্লেট

### টেমপ্লেট T-1: ইউজার ফিচার (তথ্য দেখায়)
```python
# ── ZONE-A তে (main_menu) ──
kb.append([{"text": "👤 MY ACCOUNT", "style": "primary"}])
# USER_MENU_BUTTONS লিস্টেও "👤 MY ACCOUNT" যোগ করুন

# ── ZONE-B তে (handle_message এর শেষে) ──
elif text == "👤 MY ACCOUNT":
    u_data = get_user(chat_id)
    send_message(chat_id, render_body_text(
        f"{PEM['user']} <b>MY ACCOUNT</b>\n"
        f"━━━━━━━━━━━━━━\n"
        f"🆔 ID: <code>{chat_id}</code>\n"
        f"💰 Balance: {u_data.get('balance', 0.0)} ৳\n"
        f"🤝 Refers: {u_data.get('total_refers', 0)}"),
        reply_markup=main_menu(chat_id))
```

### টেমপ্লেট T-2: ইউজার ফিচার (ইনপুট নেয়)
```python
# ── ZONE-A তে বাটন + USER_MENU_BUTTONS এ নাম ──
# ── ZONE-B তে (handle_message এর শেষে) ──
elif text == "📝 MY FORM":
    user_states[chat_id] = "wait_for_my_form"      # স্টেট শুরু
    temp_data[chat_id] = {}
    send_message(chat_id, render_body_text("📝 আপনার তথ্য পাঠান:"), reply_markup=get_cancel_kb())

# ── ZONE-C তে (handle_message এর স্টেট-চেইনের শেষে) ──
elif state == "wait_for_my_form" and text:
    value = text.strip()
    # ...এখানে value দিয়ে আপনার কাজ...
    send_message(chat_id, render_body_text(f"{PEM['ok']} সেভ হয়েছে: {value}"), reply_markup=main_menu(chat_id))
    del user_states[chat_id]
    del temp_data[chat_id]
    return
```

### টেমপ্লেট T-3: অ্যাডমিন প্যানেলে নতুন স্ক্রিন
```python
# ── ZONE-D তে (admin_panel_keyboard) ──
[{"text": "📊 BOT STATS", "icon_custom_emoji_id": "5353032893096567467", "callback_data": "adm_bot_stats", "style": "success"}],

# ── ZONE-E তে (handle_callback এর শেষে) ──
elif data == "adm_bot_stats":
    if not is_admin(chat_id):
        answer_callback(call["id"], "🚫 Admins only!", show_alert=True); return
    txt = (f"📊 <b>BOT STATISTICS</b>\n"
           f"━━━━━━━━━━━━━━\n"
           f"👥 Total Users: {len(all_known_users)}\n"
           f"⏳ Pending Withdrawals: {len(pending_withdrawals)}")
    kb = {"inline_keyboard": [[{"text": "Back", "icon_custom_emoji_id": "5267490665117275176",
           "callback_data": "back_to_admin", "style": "danger"}]]}
    edit_message(chat_id, msg_id, render_body_text(txt), reply_markup=kb)
```

### টেমপ্লেট T-4: অ্যাডমিন সেটিংস (টগল ON/OFF)
```python
# ── ধাপ-১: bot_settings ডিক্টে নতুন কী যোগ করুন (ফাইলের উপরে) ──
bot_settings = {
    ...
    "auto_delete": False,     # নতুন সেটিংস
}

# ── ধাপ-২: ZONE-D2 তে (system_settings_keyboard) বাটন ──
[{"text": "AUTO DELETE: OFF", "icon_custom_emoji_id": "5190899075968441286", "callback_data": "ss_auto_delete", "style": "primary"}],

# ── ধাপ-৩: ZONE-E তে কাজ ──
elif data == "ss_auto_delete":
    bot_settings["auto_delete"] = not bot_settings.get("auto_delete", False)
    save_db()   # 🔴 সেভ করা বাধ্যতামূলক, নাহলে রিস্টার্টে হারিয়ে যাবে!
    edit_message(chat_id, msg_id, render_body_text(f"{PEM['gear']} <b>System Settings</b>"), reply_markup=system_settings_keyboard())
```

### টেমপ্লেট T-5: অ্যাডমিন সেটিংস (ইনপুট নিয়ে মান বদলায় — DXA স্টাইল)
```python
# ── ZONE-D2/D তে বাটন: callback_data = "ss_my_value" ──

# ── ZONE-E তে: ইনপুট নেওয়া শুরু ──
elif data == "ss_my_value":
    temp_data[chat_id] = {"msg_id": msg_id, "key": "my_value"}
    user_states[chat_id] = "set_my_value"
    cancel_kb = {"inline_keyboard": [[{"text": "Cancel", "icon_custom_emoji_id": "5267490665117275176", "callback_data": "cancel_dxa_edit", "style": "danger"}]]}
    edit_message(chat_id, msg_id, render_body_text("📝 নতুন মান পাঠান:"), reply_markup=cancel_kb)

# ── ZONE-C তে: ইনপুট ধরা ──
elif state == "set_my_value":
    msg_id = temp_data[chat_id]["msg_id"]
    key = temp_data[chat_id]["key"]
    bot_settings[key] = text.strip()          # সংখ্যা হলে: float(text)
    save_db()
    delete_message(chat_id, msg["message_id"])
    edit_message(chat_id, msg_id, render_body_text(f"{PEM['ok']} Updated: {key}"), reply_markup=system_settings_keyboard())
    del user_states[chat_id]
    del temp_data[chat_id]
    return
```

---

## 🏗️ ৫. সম্পূর্ণ Worked Example — "👤 MY ACCOUNT" ইউজার ফিচার (ধাপে ধাপে)

**লক্ষ্য:** ইউজার মেনুতে "👤 MY ACCOUNT" বাটন যোগ; চাপলে ব্যালেন্স ও রেফার দেখাবে।

**ধাপ-১ (ZONE-A):** `main_menu()` ফাংশনে ZONE-A কমেন্টের নিচে লিখুন:
```python
kb.append([{"text": "👤 MY ACCOUNT", "style": "primary"}])
```
আর উপরের লিস্টে:
```python
USER_MENU_BUTTONS = ["Refer", "WITHDRAWAL", "SUPPORT", "👤 MY ACCOUNT"]
```

**ধাপ-২ (ZONE-B):** `handle_message()` এর শেষে ZONE-B ব্লকের পরে (SUPPORT এর `elif` এর নিচে) লিখুন:
```python
    elif text == "👤 MY ACCOUNT":
        u_data = get_user(chat_id)
        send_message(chat_id, render_body_text(
            f"{PEM['user']} <b>MY ACCOUNT</b>\n"
            f"━━━━━━━━━━━━━━\n"
            f"🆔 ID: <code>{chat_id}</code>\n"
            f"💰 Balance: {u_data.get('balance', 0.0)} ৳\n"
            f"🤝 Total Refers: {u_data.get('total_refers', 0)}"),
            reply_markup=main_menu(chat_id))
```

ব্যাস! এই দুই ধাপই লাগে — ইনপুট লাগে না বলে ZONE-C লাগে না। ফাইল সেভ করে বট রিস্টার্ট দিন। ✅

---

## 🏗️ ৬. Worked Example — "📊 BOT STATS" অ্যাডমিন ফিচার (ধাপে ধাপে)

**ধাপ-১ (ZONE-D):** `admin_panel_keyboard()` এ ZONE-D কমেন্টের নিচে যোগ করুন:
```python
[{"text": "📊 BOT STATS", "icon_custom_emoji_id": "5353032893096567467", "callback_data": "adm_bot_stats", "style": "success"}],
```

**ধাপ-২ (ZONE-E):** `handle_callback()` এর একদম শেষে ZONE-E ব্লকের পরে যোগ করুন:
```python
    elif data == "adm_bot_stats":
        if not is_admin(chat_id):
            answer_callback(call["id"], "🚫 Admins only!", show_alert=True); return
        txt = (f"📊 <b>BOT STATISTICS</b>\n"
               f"━━━━━━━━━━━━━━\n"
               f"👥 Total Users: {len(all_known_users)}\n"
               f"⏳ Pending Withdrawals: {len(pending_withdrawals)}\n"
               f"💳 W. Methods: {len(bot_settings['w_methods'])}")
        kb = {"inline_keyboard": [[{"text": "Back", "icon_custom_emoji_id": "5267490665117275176",
               "callback_data": "back_to_admin", "style": "danger"}]]}
        edit_message(chat_id, msg_id, render_body_text(txt), reply_markup=kb)
```

`Back` বাটন `back_to_admin` এ যায় — তাই আলাদা ব্যাক-হ্যান্ডলার লাগে না। ✅

---

## 🏗️ ৭. Worked Example — "Subscription" ডামি বাটনটি সত্যিকারের ফিচার বানানো

System Settings এ ইতিমধ্যে একটি **Subscription** বাটন আছে — চাপলে বলে "This feature will be added later!" (`dummy_alert`)। এটিকে বানিয়ে ফেলুন:

**ধাপ-১:** `system_settings_keyboard()` এ বাটনটির `callback_data` বদলান:
```python
[{"text": "Subscription", "icon_custom_emoji_id": "5190899075968441286", "callback_data": "ss_subscription", "style": "success"}],
```

**ধাপ-২:** ZONE-E তে হ্যান্ডলার যোগ করুন:
```python
    elif data == "ss_subscription":
        sub_on = bot_settings.get("sub_on", False)
        txt = f"💎 <b>SUBSCRIPTION SYSTEM</b>\n\nStatus: {'ON ✅' if sub_on else 'OFF ❌'}"
        kb = {"inline_keyboard": [
            [{"text": f"STATUS: {'ON' if sub_on else 'OFF'}", "icon_custom_emoji_id": "5352694861990501856" if sub_on else "5318840353510408444", "callback_data": "ss_sub_toggle", "style": "primary"}],
            [{"text": "Back", "icon_custom_emoji_id": "5267490665117275176", "callback_data": "system_settings", "style": "danger"}]]}
        edit_message(chat_id, msg_id, render_body_text(txt), reply_markup=kb)

    elif data == "ss_sub_toggle":
        bot_settings["sub_on"] = not bot_settings.get("sub_on", False)
        save_db()
        answer_callback(call["id"], "✅ Saved!")
        edit_message(chat_id, msg_id, render_body_text(f"{PEM['gear']} <b>System Settings</b>"), reply_markup=system_settings_keyboard())
```

---

## ⚠️ ৮. গুরুত্বপূর্ণ নিয়ম ও সতর্কতা (ভুলেও ভুলবেন না!)

| # | নিয়ম | কেন |
|---|---|---|
| ১ | কিবোর্ড বাটনের নাম `USER_MENU_BUTTONS` লিস্টেও যোগ করুন | নাহলে ইনপুট-স্টেটের মাঝে বাটন চাপলে সেটি ইনপুট হিসেবে গণ্য হবে |
| ২ | সেটিংস বদলালে সবশেষে `save_db()` কল করুন | না দিলে বট রিস্টার্টে পরিবর্তন মুছে যাবে |
| ৩ | ইনপুট-স্টেট শেষে `del user_states[...]`, `del temp_data[...]` + `return` | না করলে বট সব মেসেজ ইনপুট ভেবে আটকে রাখবে |
| ৪ | ইনপুট নেওয়ার সময় `reply_markup=get_cancel_kb()` দিন | ইউজার Cancel চেপে বেরিয়ে আসতে পারে (`cancel_state` অটো-হ্যান্ডলড) |
| ৫ | সব টেক্সট `render_body_text(...)` দিয়ে পাঠান | প্রিমিয়াম ইমোজি রেন্ডার হয় এটি দিয়েই |
| ৬ | `elif` চেইনে নতুন ব্লক **সবসময় শেষে** যোগ করুন | মাঝে ঢুকিয়ে দিলে পুরনো ব্লক আটকে যেতে পারে |
| ৭ | callback-এ নির্দিষ্ট ম্যাচ আগে, `startswith` পরে | `lb_main` আগে, `lb_` পরে — এটাই প্যাটার্ন |
| ৮ | অ্যাডমিন ফিচারে `is_admin(chat_id)` চেক দিন | লিংক-ম্যানিপুলেশনে সাধারণ ইউজার ঢুকতে পারে না, তবুও নিরাপদ থাকুন |
| ৯ | ইউজারের দেখা টেক্সটে HTML ব্যবহার করলে `<b>`, `<code>` ঠিক রাখুন | parse_mode="HTML" চালু আছে — ভাঙা ট্যাগে মেসেজ ফেল করবে |
| ১০ | নতুন `callback_data` অন্য বাটনের সাথে কনফ্লিক্ট করাবেন না | ইউনিক প্রিফিক্স দিন: `adm_`, `ss_`, `um_`, `md_` ইত্যাদি আগে থেকেই ব্যবহৃত |

---

## 💾 ৯. ডেটা সেভ করার নিয়ম (Firestore + Local)

**নতুন সেটিংস** (যেমন `sub_on`) স্থায়ীভাবে রাখতে:

```python
# ১) ফাইলের উপরে bot_settings ডিক্টে ডিফল্ট মান যোগ করুন
bot_settings = {
    ...
    "sub_on": False,
}

# ২-a) শুধু লোকাল রাখতে চাইলে (রিস্টার্টে থাকবে, Firestore এ যাবে না): ব্যস — save_db() ই যথেষ্ট
# ২-b) Firestore এও সিঙ্ক করতে চাইলে FS_KEYS লিস্টে কী-এর নাম যোগ করুন:
FS_KEYS = [
    "admins", "withdraw_on",
    "min_withdraw", "refer_reward",
    "support_link", "w_methods", "w_group",
    "fj_on", "fj_channels",
    "sub_on"          # ← নতুন
]
```

**ইউজারের প্রাইভেট ডেটা** (প্রতি-ইউজার আলাদা) রাখতে Firestore ব্যবহার করুন:
```python
db.collection('my_feature_data').document(str(chat_id)).set({"key": value})
doc = db.collection('my_feature_data').document(str(chat_id)).get()
```

**অস্থায়ী ডেটা** (শুধু এই মুহূর্তের জন্য — ইনপুট ফ্লো): `temp_data[chat_id]` ব্যবহার করুন; কাজ শেষে মুছে দিন।

---

## ✅ ১০. ফিচার যোগ করার ফাইনাল চেকলিস্ট

- [ ] বাটন যোগ হয়েছে সঠিক keyboard ফাংশনে (ZONE-A / D / D2)
- [ ] কিবোর্ড বাটন হলে নাম `USER_MENU_BUTTONS` এও আছে
- [ ] বাটনের কাজ বসানো হয়েছে সঠিক handler এ (ZONE-B / E)
- [ ] ইনপুট লাগলে স্টেট ZONE-C তে ধরা হয়েছে এবং শেষে state/temp ক্লিয়ার + `return`
- [ ] সেটিংস বদলালে `save_db()` কল হচ্ছে
- [ ] অ্যাডমিন-অনলি হলে `is_admin()` চেক আছে
- [ ] নতুন `callback_data` ইউনিক এবং অন্য প্রিফিক্সের সাথে কনফ্লিক্ট নেই
- [ ] ফাইল সেভ করে `python bot.py` চালিয়ে এরর নেই কিনা দেখা হয়েছে
- [ ] টেলিগ্রামে গিয়ে বাটন চেপে পুরো ফ্লো টেস্ট করা হয়েছে

---

## 🔍 ১১. দ্রুত জায়গা খোঁজার শর্টকাট

কোডে `Ctrl+F` করে লিখুন:

| খুঁজুন | পাবেন |
|---|---|
| `ZONE-A` | ইউজার কিবোর্ড বাটনের জায়গা |
| `ZONE-A2` | অ্যাডমিন কিবোর্ড বাটনের জায়গা |
| `ZONE-B` | ইউজার বাটনের কাজের জায়গা |
| `ZONE-C` | ইনপুট ধরার জায়গা |
| `ZONE-D` | অ্যাডমিন প্যানেল বাটনের জায়গা |
| `ZONE-D2` | System Settings বাটনের জায়গা |
| `ZONE-E` | ইনলাইন বাটনের কাজের জায়গা |
| `BOT CODE MAP` | পুরো ম্যাপ (ফাইলের শুরুতে) |

> 💡 **মনে রাখুন:** বাটন (কিবোর্ড) → কাজ (handler) → ইনপুট লাগলে (state) → সেভ (save_db)। এই ৪টি ধাপই প্রতিটি ফিচারের পূর্ণ সূত্র।

---

## 💳 ১২. LIVE EXAMPLE — Account System + Link Buttons (Support/Community)

বটে ইতিমধ্যেই এই সূত্র দিয়ে **দুটো সম্পূর্ণ ফিচার** বানানো আছে — নতুন কিছু লিখার আগে এই ফিচারগুলোর কোড দেখে নিলেই প্যাটার্ন পরিষ্কার হয়ে যাবে।

### ফিচার ১: 💳 Account + 📜 Transaction History (FEATURE MODULE #1)

- **ইউজার:** 💳 **Account** বাটন (মেনুর সবার উপরে) → Username, User ID, Balance, Available Balance, Pending Balance, Total Withdrawal দেখায়
- **📜 Transaction History** বাটন → উইথড্র হিস্ট্রি (✅ Approved / ⌛ Pending / ❌ Rejected) + রেফার ইনকাম — সব তারিখসহ
- **অ্যাডমিন:** উইথড্র রিকোয়েস্ট APPROVE/REJECT করলেই হিস্ট্রি অটো-আপডেট হয়; Reject করলে টাকা **অটো-রিফান্ড** হয়
- রেফার ইনকাম প্রতিবার `record_refer_income()` দিয়ে Firestore-এর `refer_income` কালেকশনে সেভ হয়

### কোডটা কোন ZONE-এ বসানো হয়েছে (রেফারেন্স ম্যাপ)

| ফিচারের অংশ | ZONE | কোডে খুঁজতে |
|---|---|---|
| 💳 Account কিবোর্ড বাটন (রো-১) | ZONE-A | `kb.append([{"text": "💳 Account"` |
| `USER_MENU_BUTTONS` লিস্ট এন্ট্রি | — | `USER_MENU_BUTTONS = ["💳 Account", ...]` |
| Account স্ক্রিন (Username + ৪ ব্যালেন্স) | ZONE-B | `elif text == "💳 Account":` |
| 📜 Transaction History বাটনের কাজ | ZONE-E | `elif data == "acc_history":` |
| ব্যালেন্স হিসাব (pending/approved যোগফল) | MODULE #1 | `_acc_pending_amount`, `_acc_total_withdrawn` |
| হিস্ট্রি টেক্সট + ফেচ | MODULE #1 | `transaction_history_text`, `_acc_fetch_history` |
| রেফার ইনকাম সেভ | USER BACKEND | `record_refer_income(` |
| স্ক্রিনের লেখা (DRY) | MODULE #1 | `account_screen_text`, `account_keyboard` |

### ফিচার ২: 💬 Support Buttons / 👥 Community (FEATURE MODULE #2)

- **অ্যাডমিন:** Admin Panel → **Support Buttons** / **Community** → ➕ Add Button → পাঠান `Button Text - https://link.com` → বাটন সেভ হবে (🗑 দিয়ে ডিলিট)
- **ইউজার:** **SUPPORT** / **Community** বাটন → অ্যাডমিনের বানানো বাটনগুলো দেখাবে → ক্লিক করলে সাপোর্ট চ্যাট / টেলিগ্রাম গ্রুপ-চ্যানেল ওপেন হবে
- Support-এ কোনো বাটন না থাকলে পুরনো `support_link` (DXA Control) ফলব্যাক হিসেবে দেখায়

| ফিচারের অংশ | ZONE | কোডে খুঁজতে |
|---|---|---|
| SUPPORT / Community কিবোর্ড বাটন (রো-৩) | ZONE-A | `# রো-৩: SUPPORT | Community` |
| SUPPORT হ্যান্ডলার (বাটন লিস্ট + ফলব্যাক) | ZONE-B | `elif text == "SUPPORT":` |
| Community হ্যান্ডলার | ZONE-B | `elif text == "Community":` |
| অ্যাডমিন প্যানেল বাটন (ম্যানেজার) | ZONE-D | `"callback_data": "manage_sb"` / `"manage_cb"` |
| manage_sb / sb_add / sb_del_ কাজ | ZONE-E | `# 🧩 FEATURE MODULE #2 হুক` |
| বাটন অ্যাড ইনপুট স্টেট | ZONE-C | `wait_for_add_sb` / `wait_for_add_cb` |
| হেল্পার (parse/keyboard) | MODULE #2 | `_lb_parse`, `_link_buttons_keyboard` |
| সেটিংস সেভ | bot_settings + FS_KEYS | `"support_buttons"`, `"community_buttons"` |

### বাটন ফরম্যাট ভ্যালিডেশন (`_lb_parse`)

| অ্যাডমিন লিখেছে | ফলাফল |
|---|---|
| `Contact Admin - https://t.me/xyz` | ✅ সঠিক |
| `Our Channel - https://t.me/xyz` | ✅ সঠিক (প্রথম ড্যাশেই কাটা হয়, নামে ড্যাশ থাকলেও চলে) |
| `X - tg://resolve?domain=abc` | ✅ সঠিক (tg:// লিংকও চলে) |
| `X - ftp://bad` | ❌ (শুধু http/https/tg:// চলে) |
| `লিংক ছাড়া লেখা` | ❌ (স্টেট থাকে — আবার পাঠানো যায়) |

> 💡 নতুন ফিচার বানানোর আগে `Ctrl+F` → `FEATURE MODULE #1` লিখে এই লাইভ উদাহরণের প্রতিটি অংশ দেখে নিন — হুবহু একই প্যাটার্নে আপনার ফিচার বসান।

---

## 🧩 ১৩. FEATURE MODULE প্যাটার্ন — একাধিক সিস্টেম গুছিয়ে বসানোর নিয়ম

বড় ফিচার অনেকগুলো যোগ করতে থাকলে কোড এলোমেলো হয়ে যেতে পারে। তাই bot.py-তে এখন
**FEATURE MODULE** প্যাটার্ন ব্যবহার করা হয় — প্রতিটা সিস্টেমের সব কোড একটা নির্দিষ্ট ব্লকে থাকে।

### ফাইলের নতুন বিন্যাস (BOT CODE MAP ব্যানারেও আছে)

| অংশ | কী থাকে | কোথায় |
|---|---|---|
| 5️⃣ KEYBOARDS | main_menu + অ্যাডমিন কিবোর্ড (ZONE-A/A2/D/D2 এখানে) | মাঝামাঝি |
| 6️⃣ FEATURE MODULES | প্রতি সিস্টেমের helper + keyboard এক ব্লকে | keyboards-এর পরে, handle_message-এর আগে |
| 7️⃣ handle_message | ZONE-B (বাটনের কাজ) + ZONE-C (ইনপুট স্টেট) | এরপর |
| 8️⃣ handle_callback | ZONE-E (ইনলাইন বাটনের কাজ) + মডিউল হুক | এরপর |

### নতুন সিস্টেম বসানোর ৩-ধাপ রেসিপি

1. **ব্লক খুলুন:** `Ctrl+F` → `FEATURE MODULE #3` — ওই মার্কারের নিচে আপনার সিস্টেমের
   সব helper + keyboard ফাংশন লিখুন। ব্লকের মাথায় নম্বর বাড়িয়ে ব্যানার দিন:
   `# 🧩 FEATURE MODULE #4 | আপনার সিস্টেমের নাম`
2. **ZONE হুক বসান:** বাটন → ZONE-A/A2/D/D2; কাজ → ZONE-B/E; ইনপুট লাগলে → ZONE-C।
3. **সেটিংস:** নতুন ডেটা লাগলে `bot_settings` + `FS_KEYS` দুই জায়গায়ই নাম যোগ করুন।

### লাইভ উদাহরণ — দুইটা FEATURE MODULE একসাথে

এখন দুটো মডিউল চলে — এটাই "একাধিক সিস্টেম গুছিয়ে রাখার" নমুনা:

| মডিউল | helper/keyboard | হুক |
|---|---|---|
| #1 ACCOUNT SYSTEM | `account_screen_text`, `account_keyboard`, `transaction_history_text`, `_acc_pending_amount`, `_acc_total_withdrawn`, `record_refer_income` | `💳 Account` (ZONE-B), `acc_history` / `back_to_account` (ZONE-E) |
| #2 LINK BUTTONS | `_lb_parse`, `_link_buttons_keyboard`, `support_admin_keyboard`, `community_admin_keyboard` | `SUPPORT` / `Community` (ZONE-B), `manage_sb` / `manage_cb` (ZONE-D→E), `wait_for_add_sb` / `wait_for_add_cb` (ZONE-C) |

> 💡 Account স্ক্রিনে নতুন কিছু যোগ করতে চাইলে `account_keyboard()` এ একটা রো যোগ করুন
> + ZONE-E তে কাজ বসান — `acc_history` ব্লকটা হুবহু নমুনা হিসেবে কপি করতে পারেন।
> নতুন ইউজার কিবোর্ড বাটন লাগলে ZONE-A + USER_MENU_BUTTONS দুটোতেই নাম দিন (নিয়ম ১)।
