#!/usr/bin/env python3
"""
Lau Jing Ying (刘静颖) - Personal Finance Secretary for Sek Yin Jia
Features:
1. Native Telegram Expandable Cards (<blockquote expandable>):
   - Collapsed by default (takes only 1 glanceable line)
   - Tap to expand full accounts and itemized details
2. Inline action bar: [💳 All Balances] [📊 Open Google Sheet]
3. Expandable Receipt Confirmation Card with [✅ Save to Sheet] and [❌ Cancel]
4. Gemini Vision AI for single and multi-transaction receipts
5. Cloud REST API for Google Sheets (Render 24/7) + casual evening check-in
"""

import sys
import os
import json
import base64
import subprocess
import urllib.request
import urllib.parse
import urllib.error
import time
import random
import uuid
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from datetime import datetime

SPREADSHEET_ID = "15f_sbDn3Giga7Kg2Axf3ONQ296Ftz4QC8Se2zH0uzSE"
SHEET_URL = f"https://docs.google.com/spreadsheets/d/{SPREADSHEET_ID}/edit?gid=2071550954#gid=2071550954"
CONFIG_FILE = os.path.expanduser("~/.gemini/antigravity/scratch/finance_telegram_bot/config.json")
TOKEN_FILE = os.path.expanduser("~/.gemini/antigravity/plugin_data/gsheets/token.json")

WIZARD_SESSIONS = {}
PENDING_CONFIRMATIONS = {}

def load_config():
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, "r") as f:
            return json.load(f)
    return {}

def save_config(cfg):
    with open(CONFIG_FILE, "w") as f:
        json.dump(cfg, f, indent=2)

def get_google_access_token():
    """Retrieves fresh Google OAuth access token using refresh token."""
    client_id = os.environ.get("GOOGLE_CLIENT_ID")
    client_secret = os.environ.get("GOOGLE_CLIENT_SECRET")
    refresh_token = os.environ.get("GOOGLE_REFRESH_TOKEN")

    if not (client_id and client_secret and refresh_token) and os.path.exists(TOKEN_FILE):
        try:
            with open(TOKEN_FILE, "r") as f:
                t_data = json.load(f)
                client_id = t_data.get("client_id")
                client_secret = t_data.get("client_secret")
                refresh_token = t_data.get("token", {}).get("refresh_token")
        except:
            pass

    if not (client_id and client_secret and refresh_token):
        return None

    try:
        req_data = urllib.parse.urlencode({
            "client_id": client_id,
            "client_secret": client_secret,
            "refresh_token": refresh_token,
            "grant_type": "refresh_token"
        }).encode("utf-8")
        req = urllib.request.Request("https://oauth2.googleapis.com/token", data=req_data)
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())
            return data.get("access_token")
    except Exception as e:
        print(f"Error refreshing Google token: {e}")
        return None

def fetch_latest_finance_data():
    """Reads latest balances and transactions from Google Sheets."""
    access_token = get_google_access_token()
    rows = []

    if access_token:
        try:
            range_enc = urllib.parse.quote("'2026 Oct Basic Acc 1'!A1:L35")
            url = f"https://sheets.googleapis.com/v4/spreadsheets/{SPREADSHEET_ID}/values/{range_enc}"
            req = urllib.request.Request(url, headers={"Authorization": f"Bearer {access_token}"})
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read().decode())
                rows = data.get("values", [])
        except Exception as e:
            print(f"REST API read failed: {e}")

    if not rows:
        cmd = ["gsheets", "readonly", "read", SPREADSHEET_ID, "'2026 Oct Basic Acc 1'!A1:L35", "--json"]
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, check=True)
            rows = json.loads(proc.stdout)
        except Exception as e:
            print(f"CLI read failed: {e}")
            return None

    transactions = []
    latest_balances = {
        "Cash": rows[1][6].strip() if len(rows) > 1 and len(rows[1]) > 6 else "RM 0.00",
        "EWallet": rows[1][7].strip() if len(rows) > 1 and len(rows[1]) > 7 else "RM 0.00",
        "Maybank": rows[1][8].strip() if len(rows) > 1 and len(rows[1]) > 8 else "RM 0.00",
        "RHB": rows[1][9].strip() if len(rows) > 1 and len(rows[1]) > 9 else "RM 0.00",
        "PMO": rows[1][10].strip() if len(rows) > 1 and len(rows[1]) > 10 else "RM 0.00",
        "Total": rows[1][11].strip() if len(rows) > 1 and len(rows[1]) > 11 else "RM 0.00",
    }

    for r in rows[3:]:
        if len(r) > 0 and r[0].strip():
            date = r[0].strip()
            credit = r[1].strip() if len(r) > 1 else ""
            debit = r[2].strip() if len(r) > 2 else ""
            type_ = r[3].strip() if len(r) > 3 else ""
            event = r[4].strip() if len(r) > 4 else ""
            note = r[5].strip() if len(r) > 5 else ""
            
            if len(r) > 7 and r[7].strip(): latest_balances["EWallet"] = r[7].strip()
            if len(r) > 8 and r[8].strip(): latest_balances["Maybank"] = r[8].strip()
            if len(r) > 9 and r[9].strip(): latest_balances["RHB"] = r[9].strip()
            if len(r) > 10 and r[10].strip(): latest_balances["PMO"] = r[10].strip()
            if len(r) > 11 and r[11].strip(): latest_balances["Total"] = r[11].strip()

            transactions.append({
                "date": date,
                "credit": credit,
                "debit": debit,
                "type": type_,
                "event": event,
                "note": note
            })

    return {
        "balances": latest_balances,
        "recent_tx": transactions
    }

def append_transactions_to_sheet(tx_list):
    """Appends transactions into Google Sheets."""
    if not isinstance(tx_list, list):
        tx_list = [tx_list]

    access_token = get_google_access_token()
    vals = []

    if access_token:
        try:
            range_enc = urllib.parse.quote("'2026 Oct Basic Acc 1'!A4:F50")
            url = f"https://sheets.googleapis.com/v4/spreadsheets/{SPREADSHEET_ID}/values/{range_enc}"
            req = urllib.request.Request(url, headers={"Authorization": f"Bearer {access_token}"})
            with urllib.request.urlopen(req, timeout=15) as resp:
                vals = json.loads(resp.read().decode()).get("values", [])
        except Exception as e:
            print(f"REST read error: {e}")

    if not vals:
        cmd_read = ["gsheets", "readonly", "read", SPREADSHEET_ID, "'2026 Oct Basic Acc 1'!A4:F50", "--json"]
        proc = subprocess.run(cmd_read, capture_output=True, text=True, check=True)
        vals = json.loads(proc.stdout)

    filled_count = 0
    for idx, r in enumerate(vals):
        if len(r) > 0 and r[0].strip():
            filled_count = idx + 1
    start_row = 4 + filled_count
    end_row = start_row + len(tx_list) - 1

    formatted_rows = []
    for tx in tx_list:
        credit_val = ""
        debit_val = ""
        if tx.get("credit"):
            try:
                amt = float(str(tx["credit"]).replace("RM", "").replace(",", "").strip())
                credit_val = f" RM {amt:.2f} "
            except:
                credit_val = f" {tx['credit']} "

        if tx.get("debit"):
            try:
                amt = float(str(tx["debit"]).replace("RM", "").replace(",", "").strip())
                debit_val = f" RM {amt:.2f} "
            except:
                debit_val = f" {tx['debit']} "

        formatted_rows.append([
            tx.get("date", ""),
            credit_val,
            debit_val,
            tx.get("type", "E Wallet"),
            tx.get("event", "Meal"),
            tx.get("note", "")
        ])

    if access_token:
        range_target = urllib.parse.quote(f"'2026 Oct Basic Acc 1'!A{start_row}:F{end_row}")
        put_url = f"https://sheets.googleapis.com/v4/spreadsheets/{SPREADSHEET_ID}/values/{range_target}?valueInputOption=USER_ENTERED"
        payload = {
            "range": f"'2026 Oct Basic Acc 1'!A{start_row}:F{end_row}",
            "majorDimension": "ROWS",
            "values": formatted_rows
        }
        req_put = urllib.request.Request(
            put_url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"},
            method="PUT"
        )
        with urllib.request.urlopen(req_put, timeout=15) as resp:
            pass
    else:
        batch_payload = [
            {
                "op": "write",
                "range": f"'2026 Oct Basic Acc 1'!A{start_row}:F{end_row}",
                "data": formatted_rows
            }
        ]
        tmp_file = f"/tmp/gsheets_add_rows_{int(time.time()*1000)}.json"
        with open(tmp_file, "w") as f:
            json.dump(batch_payload, f)
        cmd_write = ["gsheets", "mutate", "batch", SPREADSHEET_ID, "-f", tmp_file, "--json"]
        subprocess.run(cmd_write, capture_output=True, text=True, check=True)
        if os.path.exists(tmp_file):
            os.remove(tmp_file)

    return (start_row, end_row)

def format_daily_report_card(data):
    """
    Renders an expandable card:
    - 1-line glance preview when collapsed
    - Full accounts, daily average, and items when tapped
    """
    today = datetime.now()
    today_str = f"{today.day}-{today.strftime('%b')}-{today.year}"
    
    living_expenses = []
    today_items = []
    today_total = 0.0
    
    for tx in data["recent_tx"]:
        if tx["debit"]:
            try:
                amt = float(tx["debit"].replace("RM", "").replace(",", "").strip())
                event = tx["event"] or "Other"
                if event.lower() not in ["rental", "transfer", "investment", "loss"]:
                    living_expenses.append(amt)
                
                if tx["date"] == today_str:
                    today_total += amt
                    today_items.append((event, tx["note"] or tx["type"], amt))
            except:
                pass
                
    day_of_month = max(1, today.day)
    month_living_total = sum(living_expenses)
    daily_avg = month_living_total / day_of_month
    
    if today_total <= daily_avg:
        trend = f"🟢 RM {abs(today_total - daily_avg):.2f} under avg"
    else:
        trend = f"🟡 RM {abs(today_total - daily_avg):.2f} above avg"
    
    b = data["balances"]
    
    today_item_lines = ""
    if today_items:
        today_item_lines = "\n<b>Today's Spending:</b>\n" + "\n".join([f"• {c} ({n}): RM {a:.2f}" for c, n, a in today_items])
    else:
        today_item_lines = "\n<i>No expenses recorded yet today.</i>"

    # Native expandable blockquote HTML
    card = (
        "Hey! Here is your daily spend snapshot ✨\n\n"
        "<blockquote expandable>"
        f"📊 <b>Today: RM {today_total:.2f} ({trend}) | E-Wallet: {b['EWallet']}</b>\n"
        "────────────────────\n"
        f"• Oct Daily Avg: RM {daily_avg:.2f}/day\n"
        f"{today_item_lines}\n\n"
        "<b>Accounts Breakdown:</b>\n"
        f"• 📱 E-Wallet: {b['EWallet']}\n"
        f"• 💳 Maybank: {b['Maybank']}\n"
        f"• 🏛️ RHB: {b['RHB']}\n"
        f"• 💵 Cash: {b['Cash']}\n"
        f"• 📈 PMO: {b['PMO']}\n"
        f"• 💰 Net Worth: {b['Total']}\n"
        "</blockquote>"
    )

    buttons = {
        "inline_keyboard": [[
            {"text": "💳 All Balances", "callback_data": "cmd:balance"},
            {"text": "📊 Open Google Sheet", "url": SHEET_URL}
        ]]
    }

    return card, buttons

def format_balances_card(data):
    """Expandable card for /balance."""
    b = data["balances"]
    card = (
        "Here's your current balance check ✨\n\n"
        "<blockquote expandable>"
        f"💰 <b>Net Worth: {b['Total']} | E-Wallet: {b['EWallet']}</b>\n"
        "────────────────────\n"
        f"• 📱 E-Wallet: {b['EWallet']}\n"
        f"• 💳 Maybank: {b['Maybank']}\n"
        f"• 🏛️ RHB Bank: {b['RHB']}\n"
        f"• 💵 Cash: {b['Cash']}\n"
        f"• 📈 PMO Investment: {b['PMO']}\n"
        "</blockquote>"
    )
    buttons = {
        "inline_keyboard": [[
            {"text": "📊 Open Google Sheet", "url": SHEET_URL}
        ]]
    }
    return card, buttons

def format_recent_card(data):
    lines = []
    for tx in reversed(data["recent_tx"][-7:]):
        amt = f"+{tx['credit']}" if tx['credit'] else f"-{tx['debit']}"
        lines.append(f"• <b>{tx['date']}</b> | {tx['event']} ({tx['note'] or tx['type']}): <code>{amt}</code>")
    
    top_line = lines[0] if lines else "• No recent records."
    card = (
        "Here are your latest records ✨\n\n"
        "<blockquote expandable>"
        f"📝 <b>Latest: {top_line}</b>\n"
        "────────────────────\n"
        + "\n".join(lines) + "\n"
        "</blockquote>"
    )
    return card

def send_telegram_message(token, chat_id, text, reply_markup=None):
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True
    }
    if reply_markup:
        payload["reply_markup"] = reply_markup
    
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode())
    except Exception as e:
        print(f"Error sending message: {e}")
        return None

def edit_telegram_message(token, chat_id, message_id, text, reply_markup=None):
    url = f"https://api.telegram.org/bot{token}/editMessageText"
    payload = {
        "chat_id": chat_id,
        "message_id": message_id,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True
    }
    if reply_markup is not None:
        payload["reply_markup"] = reply_markup
    
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode())
    except Exception as e:
        print(f"Error editing message: {e}")
        return None

def answer_callback_query(token, callback_query_id, text=None):
    url = f"https://api.telegram.org/bot{token}/answerCallbackQuery"
    payload = {"callback_query_id": callback_query_id}
    if text:
        payload["text"] = text
    req = urllib.request.Request(url, data=json.dumps(payload).encode('utf-8'), headers={"Content-Type": "application/json"})
    try:
        urllib.request.urlopen(req, timeout=10)
    except:
        pass

def download_telegram_photo(token, file_id):
    info_url = f"https://api.telegram.org/bot{token}/getFile?file_id={file_id}"
    req = urllib.request.Request(info_url)
    with urllib.request.urlopen(req, timeout=15) as resp:
        data = json.loads(resp.read().decode())
    file_path = data["result"]["file_path"]
    download_url = f"https://api.telegram.org/file/bot{token}/{file_path}"
    with urllib.request.urlopen(download_url, timeout=20) as resp:
        return resp.read()

def parse_receipt_with_gemini(image_bytes, gemini_api_key):
    """Gemini Vision extraction with strict Malaysian financial context."""
    b64_img = base64.b64encode(image_bytes).decode("utf-8")
    
    prompt = """
You are Lau Jing Ying, an expert Malaysian personal finance assistant.
Extract all valid financial transactions from this payment receipt, eWallet confirmation (Touch 'n Go, GrabPay, Boost, ShopeePay), or banking transfer slip (Maybank MAE, RHB).

RULES:
1. Extract ALL valid transactions into the "transactions" array (supports 1 or multiple items).
2. Exclude internal transfers/reloads between user's own accounts unless an explicit topup.
3. If not a financial receipt, return is_valid: false.

FIELDS:
- is_expense: (boolean) true for payments, false for income/reloads.
- date: STRICT "D-Mmm-YYYY" (e.g. "11-Oct-2026").
- amount: Float MYR value (e.g. 12.50).
- type: EXACTLY one of: "E Wallet", "Maybank", "RHB", "Cash", "PMO".
- event: EXACTLY one of: "Meal", "Grocery", "Transportation", "Subscription fee", "Online Shopping", "Entertainment", "Electric & Water Bills", "Rental", "Transfer", "Reload".
- note: Clean Merchant or Payee name (e.g. "Kim Seng Mixed Rice", "KK Mart", "Starbucks"). Max 35 chars.

OUTPUT STRICT JSON:
{
  "is_valid": true,
  "transactions": [
    {
      "is_expense": true,
      "date": "11-Oct-2026",
      "amount": 12.50,
      "type": "E Wallet",
      "event": "Meal",
      "note": "Kim Seng Mixed Rice"
    }
  ]
}
"""

    models_to_try = ["gemini-2.5-flash", "gemini-1.5-flash", "gemini-2.0-flash"]
    last_err = None

    for model in models_to_try:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={gemini_api_key}"
        payload = {
            "contents": [
                {
                    "parts": [
                        {"text": prompt},
                        {
                            "inline_data": {
                                "mime_type": "image/jpeg",
                                "data": b64_img
                            }
                        }
                    ]
                }
            ],
            "generationConfig": {
                "response_mime_type": "application/json",
                "temperature": 0.1
            }
        }
        try:
            req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"), headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=30) as resp:
                resp_json = json.loads(resp.read().decode())
                cand = resp_json["candidates"][0]["content"]["parts"][0]["text"]
                return json.loads(cand)
        except Exception as e:
            last_err = e
            continue

    raise Exception(f"Gemini API error: {last_err}")

# Lightweight health server for Render
class HealthServer(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.end_headers()
        self.wfile.write(b"Lau Jing Ying is online 24/7!\n")
    def log_message(self, format, *args):
        return

def start_health_server():
    port = int(os.environ.get("PORT", 8080))
    server = HTTPServer(("0.0.0.0", port), HealthServer)
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    print(f"Health server running on port {port}")

def evening_checkin_scheduler(token, chat_id):
    """Casual random evening check-in around 8:30 PM - 10:15 PM once a day."""
    last_sent_date = ""
    while True:
        try:
            now = datetime.now()
            today_str = now.strftime("%Y-%m-%d")
            # Window between 20:30 and 22:15
            if today_str != last_sent_date and (now.hour == 21 or (now.hour == 20 and now.minute >= 45)):
                # Random delay 0-25 mins
                time.sleep(random.randint(0, 1500))
                data = fetch_latest_finance_data()
                if data:
                    card, buttons = format_daily_report_card(data)
                    send_telegram_message(token, chat_id, card, reply_markup=buttons)
                    last_sent_date = today_str
            time.sleep(900)  # Check every 15 mins
        except:
            time.sleep(60)

def run_bot_service():
    start_health_server()
    cfg = load_config()
    token = os.environ.get("TELEGRAM_BOT_TOKEN") or cfg.get("bot_token")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID") or cfg.get("chat_id")

    if not token:
        print("Bot token missing")
        return

    # Start casual scheduler
    if chat_id:
        t_sched = threading.Thread(target=evening_checkin_scheduler, args=(token, chat_id), daemon=True)
        t_sched.start()

    print("Lau Jing Ying bot service started. Polling Telegram...")
    last_update_id = 0

    try:
        cmd_url = f"https://api.telegram.org/bot{token}/setMyCommands"
        cmds = {
            "commands": [
                {"command": "report", "description": "Quick spend check card"},
                {"command": "balance", "description": "Check current balances"},
                {"command": "add", "description": "Log an expense (/add 8.00 Meal note)"},
                {"command": "recent", "description": "Last records"},
                {"command": "help", "description": "Quick guide"}
            ]
        }
        req = urllib.request.Request(cmd_url, data=json.dumps(cmds).encode('utf-8'), headers={"Content-Type": "application/json"})
        urllib.request.urlopen(req, timeout=10)
    except:
        pass

    while True:
        try:
            url = f"https://api.telegram.org/bot{token}/getUpdates?offset={last_update_id + 1}&timeout=30"
            with urllib.request.urlopen(url, timeout=35) as resp:
                data = json.load(resp)
                for update in data.get("result", []):
                    last_update_id = update["update_id"]

                    # 1. Handle Inline Button Callbacks
                    if "callback_query" in update:
                        cb = update["callback_query"]
                        cb_id = cb["id"]
                        cb_data = cb.get("data", "")
                        cb_chat_id = cb["message"]["chat"]["id"]
                        cb_msg_id = cb["message"]["message_id"]

                        if cb_data == "cmd:balance":
                            answer_callback_query(token, cb_id)
                            f_data = fetch_latest_finance_data()
                            if f_data:
                                card, buttons = format_balances_card(f_data)
                                send_telegram_message(token, cb_chat_id, card, reply_markup=buttons)

                        elif cb_data.startswith("confirm:"):
                            confirm_id = cb_data.split(":", 1)[1]
                            tx_items = PENDING_CONFIRMATIONS.pop(confirm_id, None)
                            if tx_items:
                                answer_callback_query(token, cb_id, "Saving...")
                                try:
                                    s_row, e_row = append_transactions_to_sheet(tx_items)
                                    row_text = f"Row #{s_row}" if s_row == e_row else f"Rows #{s_row}–#{e_row}"
                                    tot = sum([float(t.get("debit") or 0) for t in tx_items])
                                    
                                    if len(tx_items) == 1:
                                        t = tx_items[0]
                                        msg = f"Done! Saved <b>RM {tot:.2f}</b> ({t['event']} - {t['note'] or '-'}) to {row_text} 👍"
                                    else:
                                        msg = f"Done! Saved all {len(tx_items)} items (<b>RM {tot:.2f}</b> total) to {row_text} 👍"

                                    edit_telegram_message(token, cb_chat_id, cb_msg_id, msg, reply_markup=None)
                                except Exception as e:
                                    edit_telegram_message(token, cb_chat_id, cb_msg_id, f"Oops, couldn't write to sheet: {e}")
                            else:
                                answer_callback_query(token, cb_id, "Expired or already saved.")

                        elif cb_data.startswith("cancel:"):
                            confirm_id = cb_data.split(":", 1)[1]
                            PENDING_CONFIRMATIONS.pop(confirm_id, None)
                            answer_callback_query(token, cb_id, "Cancelled")
                            edit_telegram_message(token, cb_chat_id, cb_msg_id, "No worries, skipped it! 👌")

                        elif cb_data.startswith("wiz_cat:"):
                            cat = cb_data.split(":", 1)[1]
                            sess = WIZARD_SESSIONS.get(cb_chat_id)
                            if sess:
                                sess["event"] = cat
                                sess["step"] = "account"
                                answer_callback_query(token, cb_id)
                                acc_kb = {
                                    "inline_keyboard": [
                                        [{"text": "📱 E-Wallet", "callback_data": "wiz_acc:E Wallet"},
                                         {"text": "💳 Maybank", "callback_data": "wiz_acc:Maybank"}],
                                        [{"text": "💵 Cash", "callback_data": "wiz_acc:Cash"},
                                         {"text": "🏛️ RHB", "callback_data": "wiz_acc:RHB"}]
                                    ]
                                }
                                edit_telegram_message(token, cb_chat_id, cb_msg_id, f"Category: <b>{cat}</b>\n\nWhich account?", reply_markup=acc_kb)

                        elif cb_data.startswith("wiz_acc:"):
                            acc = cb_data.split(":", 1)[1]
                            sess = WIZARD_SESSIONS.get(cb_chat_id)
                            if sess:
                                sess["type"] = acc
                                sess["step"] = "note"
                                answer_callback_query(token, cb_id)
                                edit_telegram_message(token, cb_chat_id, cb_msg_id,
                                    f"<b>{sess['event']}</b> via <b>{acc}</b>\n\nAny note or merchant? (e.g. <code>Kim Seng</code>, or reply <code>skip</code>):"
                                )
                        continue

                    msg = update.get("message", {})
                    chat_id = msg.get("chat", {}).get("id")
                    text = msg.get("text", "").strip()

                    if not chat_id:
                        continue

                    # 2. Handle Photo Upload (Receipt or Statement)
                    if "photo" in msg:
                        send_telegram_message(token, chat_id, "Looking at your receipt... 🔍")
                        cfg = load_config()
                        g_key = os.environ.get("GEMINI_API_KEY") or cfg.get("gemini_api_key")

                        if not g_key:
                            send_telegram_message(token, chat_id, "Need your Gemini API key first! Use <code>/set_gemini_key KEY</code>")
                            continue

                        try:
                            file_id = msg["photo"][-1]["file_id"]
                            img_bytes = download_telegram_photo(token, file_id)
                            parsed = parse_receipt_with_gemini(img_bytes, g_key)

                            if not parsed.get("is_valid"):
                                send_telegram_message(token, chat_id, "Couldn't spot any transactions on that slip. Mind retaking it? 🧐")
                                continue

                            tx_list = parsed.get("transactions", [])
                            if not tx_list and "amount" in parsed:
                                tx_list = [parsed]

                            if not tx_list:
                                send_telegram_message(token, chat_id, "No expenses found in that photo!")
                                continue

                            c_id = str(uuid.uuid4())[:8]
                            to_record = []
                            preview_lines = []
                            total_debit = 0.0

                            for idx, tx in enumerate(tx_list, 1):
                                amt = float(tx.get("amount", 0))
                                is_exp = tx.get("is_expense", True)
                                if is_exp: total_debit += amt
                                amt_str = f"-RM {amt:.2f}" if is_exp else f"+RM {amt:.2f}"
                                
                                to_record.append({
                                    "date": tx.get("date", datetime.now().strftime("%-d-%b-%Y")),
                                    "credit": "" if is_exp else amt,
                                    "debit": amt if is_exp else "",
                                    "type": tx.get("type", "E Wallet"),
                                    "event": tx.get("event", "Meal"),
                                    "note": tx.get("note", "")
                                })
                                preview_lines.append(f"• <b>{tx.get('event')}</b>: <code>{amt_str}</code> ({tx.get('note') or '-'})")

                            PENDING_CONFIRMATIONS[c_id] = to_record

                            # Expandable receipt confirmation card
                            if len(to_record) == 1:
                                t = to_record[0]
                                card_text = (
                                    "Got it! Here is what I read ✨\n\n"
                                    "<blockquote expandable>"
                                    f"🧾 <b>{t['note'] or t['event']}: -RM {float(t['debit'] or 0):.2f}</b>\n"
                                    "────────────────────\n"
                                    f"• Category: {t['event']}\n"
                                    f"• Account: {t['type']}\n"
                                    f"• Date: {t['date']}\n"
                                    f"• Note: {t['note'] or '-'}\n"
                                    "</blockquote>\n"
                                    "Ready to save to your sheet?"
                                )
                                btn_label = "✅ Save to Sheet"
                            else:
                                card_text = (
                                    f"Found {len(to_record)} items on this receipt ✨\n\n"
                                    "<blockquote expandable>"
                                    f"🧾 <b>{len(to_record)} Items: -RM {total_debit:.2f}</b>\n"
                                    "────────────────────\n"
                                    + "\n".join(preview_lines) + "\n"
                                    "</blockquote>\n"
                                    f"Ready to save all {len(to_record)} to your sheet?"
                                )
                                btn_label = f"✅ Save All ({len(to_record)})"

                            kb = {
                                "inline_keyboard": [[
                                    {"text": btn_label, "callback_data": f"confirm:{c_id}"},
                                    {"text": "❌ Cancel", "callback_data": f"cancel:{c_id}"}
                                ]]
                            }
                            send_telegram_message(token, chat_id, card_text, reply_markup=kb)

                        except Exception as e:
                            send_telegram_message(token, chat_id, f"Oops, had trouble reading that: {e}")
                        continue

                    # 3. Wizard steps
                    if chat_id in WIZARD_SESSIONS and not text.startswith("/"):
                        sess = WIZARD_SESSIONS[chat_id]
                        if sess.get("step") == "amount":
                            try:
                                amt = float(text.replace("RM", "").replace(",", "").strip())
                                sess["amount"] = amt
                                sess["step"] = "category"
                                cat_kb = {
                                    "inline_keyboard": [
                                        [{"text": "🍜 Meal", "callback_data": "wiz_cat:Meal"},
                                         {"text": "🛒 Grocery", "callback_data": "wiz_cat:Grocery"}],
                                        [{"text": "🚗 Transport", "callback_data": "wiz_cat:Transportation"},
                                         {"text": "📱 Sub Fee", "callback_data": "wiz_cat:Subscription fee"}],
                                        [{"text": "🛍️ Shopping", "callback_data": "wiz_cat:Online Shopping"},
                                         {"text": "⚡ Bills", "callback_data": "wiz_cat:Electric & Water Bills"}]
                                    ]
                                }
                                send_telegram_message(token, chat_id, f"RM {amt:.2f}! Which category?", reply_markup=cat_kb)
                            except:
                                send_telegram_message(token, chat_id, "Just enter the number, like <code>8.50</code>:")
                            continue

                        elif sess.get("step") == "note":
                            note_val = "" if text.lower() == "skip" else text
                            sess["note"] = note_val
                            del WIZARD_SESSIONS[chat_id]

                            today = datetime.now()
                            today_str = f"{today.day}-{today.strftime('%b')}-{today.year}"
                            c_id = str(uuid.uuid4())[:8]
                            PENDING_CONFIRMATIONS[c_id] = [{
                                "date": today_str,
                                "credit": "",
                                "debit": sess["amount"],
                                "type": sess.get("type", "E Wallet"),
                                "event": sess.get("event", "Meal"),
                                "note": note_val
                            }]

                            summary = (
                                "<blockquote expandable>"
                                f"📝 <b>{note_val or sess.get('event')}: -RM {sess['amount']:.2f}</b>\n"
                                "────────────────────\n"
                                f"• Category: {sess.get('event')}\n"
                                f"• Account: {sess.get('type')}\n"
                                f"• Date: {today_str}\n"
                                "</blockquote>\n"
                                "Ready to save to sheet?"
                            )
                            kb = {
                                "inline_keyboard": [[
                                    {"text": "✅ Save", "callback_data": f"confirm:{c_id}"},
                                    {"text": "❌ Cancel", "callback_data": f"cancel:{c_id}"}
                                ]]
                            }
                            send_telegram_message(token, chat_id, summary, reply_markup=kb)
                            continue

                    # 4. Text commands
                    if text.startswith("/set_gemini_key"):
                        parts = text.split(maxsplit=1)
                        if len(parts) > 1:
                            new_key = parts[1].strip()
                            cfg = load_config()
                            cfg["gemini_api_key"] = new_key
                            save_config(cfg)
                            send_telegram_message(token, chat_id, "Got it! Gemini key updated 👌")
                        else:
                            send_telegram_message(token, chat_id, "Send <code>/set_gemini_key YOUR_KEY</code>")

                    elif text.startswith("/add") or text.startswith("/new"):
                        parts = text.split()
                        if len(parts) >= 3:
                            try:
                                amt = float(parts[1].replace("RM", "").replace(",", ""))
                                cat = parts[2].capitalize()
                                acc = "E Wallet"
                                note = ""
                                if len(parts) >= 4:
                                    if parts[3].lower() in ["maybank", "rhb", "cash", "pmo", "ewallet", "e-wallet"]:
                                        acc_map = {"maybank": "Maybank", "rhb": "RHB", "cash": "Cash", "pmo": "PMO", "ewallet": "E Wallet", "e-wallet": "E Wallet"}
                                        acc = acc_map.get(parts[3].lower(), "E Wallet")
                                        note = " ".join(parts[4:])
                                    else:
                                        note = " ".join(parts[3:])
                                
                                today = datetime.now()
                                today_str = f"{today.day}-{today.strftime('%b')}-{today.year}"
                                c_id = str(uuid.uuid4())[:8]
                                PENDING_CONFIRMATIONS[c_id] = [{
                                    "date": today_str,
                                    "credit": "",
                                    "debit": amt,
                                    "type": acc,
                                    "event": cat,
                                    "note": note
                                }]
                                summary = (
                                    "<blockquote expandable>"
                                    f"📝 <b>{note or cat}: -RM {amt:.2f}</b>\n"
                                    "────────────────────\n"
                                    f"• Category: {cat}\n"
                                    f"• Account: {acc}\n"
                                    f"• Date: {today_str}\n"
                                    "</blockquote>\n"
                                    "Save to Google Sheet?"
                                )
                                kb = {
                                    "inline_keyboard": [[
                                        {"text": "✅ Save", "callback_data": f"confirm:{c_id}"},
                                        {"text": "❌ Cancel", "callback_data": f"cancel:{c_id}"}
                                    ]]
                                }
                                send_telegram_message(token, chat_id, summary, reply_markup=kb)
                            except Exception as e:
                                send_telegram_message(token, chat_id, "Format: <code>/add 8.00 Meal Kim Seng</code>")
                        else:
                            WIZARD_SESSIONS[chat_id] = {"step": "amount"}
                            send_telegram_message(token, chat_id, "How much did you spend? (e.g. <code>8.50</code>)")

                    elif text.startswith("/start") or text.startswith("/help"):
                        help_text = (
                            "Hey! I'm Lau Jing Ying, your finance secretary ✨\n\n"
                            "Just snap receipts to me or message:\n"
                            "• <code>/add 8.00 Meal Kim Seng</code>\n"
                            "• <code>/report</code> - Today's quick check card\n"
                            "• <code>/balance</code> - Check balances\n"
                            "• <code>/recent</code> - Latest transactions"
                        )
                        send_telegram_message(token, chat_id, help_text)

                    elif text.startswith("/report") or text.startswith("/today"):
                        f_data = fetch_latest_finance_data()
                        if f_data:
                            card, buttons = format_daily_report_card(f_data)
                            send_telegram_message(token, chat_id, card, reply_markup=buttons)
                        else:
                            send_telegram_message(token, chat_id, "Couldn't reach your sheet right now!")

                    elif text.startswith("/balance"):
                        f_data = fetch_latest_finance_data()
                        if f_data:
                            card, buttons = format_balances_card(f_data)
                            send_telegram_message(token, chat_id, card, reply_markup=buttons)
                        else:
                            send_telegram_message(token, chat_id, "Couldn't get your balances!")

                    elif text.startswith("/recent"):
                        f_data = fetch_latest_finance_data()
                        if f_data:
                            card = format_recent_card(f_data)
                            send_telegram_message(token, chat_id, card)
                        else:
                            send_telegram_message(token, chat_id, "Couldn't fetch recent items!")

        except Exception as e:
            time.sleep(2)

if __name__ == "__main__":
    run_bot_service()
