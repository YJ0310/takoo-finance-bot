#!/usr/bin/env python3
"""
Telegram Finance Bot for Sek Yin Jia (@takoo_helper_bot)
Features:
1. Daily spending trend analysis & reminder (/report, /today) - 10-second glance format
2. Real-time balance snapshot (/balance)
3. Recent transactions (/recent)
4. Manual transaction insertion UI (/add, interactive step wizard, Telegram Mini App form)
5. Screenshot / Receipt photo parsing via Google Gemini API:
   - Supports SINGLE and MULTIPLE transactions in one screenshot
   - Strict Malaysian accounting rules & verification
   - Batch confirmation [✅ Confirm & Add All]
6. Cloud-ready: Direct Google Sheets REST API + lightweight health check server for Render/Cloud hosting.
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
import uuid
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from datetime import datetime

SPREADSHEET_ID = "15f_sbDn3Giga7Kg2Axf3ONQ296Ftz4QC8Se2zH0uzSE"
SHEET_URL = f"https://docs.google.com/spreadsheets/d/{SPREADSHEET_ID}/edit?gid=2071550954#gid=2071550954"
CONFIG_FILE = os.path.expanduser("~/.gemini/antigravity/scratch/finance_telegram_bot/config.json")
TOKEN_FILE = os.path.expanduser("~/.gemini/antigravity/plugin_data/gsheets/token.json")

# In-memory storage for active wizard sessions & pending confirmations
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
    """
    Retrieves a fresh Google OAuth access token using refresh token.
    Works seamlessly on local Mac or in cloud environments via environment variables.
    """
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
    """Reads latest balances and transactions from Google Sheets using REST API or gsheets CLI fallback."""
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
    """
    Appends one or more transactions into '2026 Oct Basic Acc 1'.
    tx_list: list of dicts with keys: date, credit, debit, type, event, note
    Preserves columns G:L formulas.
    """
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
        # Fallback to local gsheets CLI
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

def format_daily_report(data):
    """10-second glance report format."""
    today = datetime.now()
    today_str = f"{today.day}-{today.strftime('%b')}-{today.year}"
    
    living_expenses = []
    today_items = []
    today_total = 0.0
    category_totals = {}
    
    for tx in data["recent_tx"]:
        if tx["debit"]:
            try:
                amt = float(tx["debit"].replace("RM", "").replace(",", "").strip())
                event = tx["event"] or "Other"
                if event.lower() not in ["rental", "transfer", "investment", "loss"]:
                    living_expenses.append(amt)
                    category_totals[event] = category_totals.get(event, 0.0) + amt
                
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
    
    top_today = max(today_items, key=lambda x: x[2]) if today_items else None
    b = data["balances"]
    
    lines = [
        f"📊 *Daily Spending Snapshot ({today.strftime('%d %b')})*",
        f"• *Today Spent:* `RM {today_total:.2f}` ({trend})",
        f"• *Oct Daily Avg:* `RM {daily_avg:.2f}/day`",
    ]
    if top_today:
        lines.append(f"• *Top Item Today:* {top_today[0]} (`RM {top_today[2]:.2f}` - {top_today[1]})")
    
    lines.extend([
        "",
        f"💳 *E-Wallet:* `{b['EWallet']}` | *Net Worth:* `{b['Total']}`",
        "",
        "🔔 *Any missed transactions today?*",
        "Send receipt photo 📸 or type `/add <amount> <category>`"
    ])
    
    return "\n".join(lines)

def format_balances(data):
    b = data["balances"]
    return "\n".join([
        "💰 *Current Balances*",
        f"• *Total Net Worth:* `{b['Total']}`",
        "────────────────────",
        f"• 📱 E-Wallet: `{b['EWallet']}`",
        f"• 📈 PMO Investment: `{b['PMO']}`",
        f"• 🏛️ RHB Bank: `{b['RHB']}`",
        f"• 💵 Cash: `{b['Cash']}`",
        f"• 💳 Maybank: `{b['Maybank']}`"
    ])

def format_recent(data):
    lines = ["📝 *Recent Transactions (October 2026):*", ""]
    for tx in reversed(data["recent_tx"][-10:]):
        amt = f"+{tx['credit']}" if tx['credit'] else f"-{tx['debit']}"
        lines.append(f"• `{tx['date']}` | *{tx['event']}* - {tx['note'] or tx['type']}: `{amt}`")
    return "\n".join(lines)

def send_telegram_message(token, chat_id, text, reply_markup=None):
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "Markdown",
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
        "parse_mode": "Markdown",
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
    """
    Extracts SINGLE or MULTIPLE financial transactions from screenshots/receipts using Gemini Vision.
    """
    b64_img = base64.b64encode(image_bytes).decode("utf-8")
    
    prompt = """
You are an expert Malaysian personal finance accountant. Analyze the provided image (which could be a single payment receipt, an eWallet/banking transaction history list with multiple items, a monthly statement snippet, or a card terminal slip).

STRICT EXTRACTION RULES:
1. SUPPORT MULTIPLE TRANSACTIONS:
   - If the image contains multiple separate payments or transactions (e.g. Touch 'n Go transaction history, Maybank statement list, or itemized receipts), extract ALL of them in the "transactions" array.
   - If it contains a single payment receipt, extract it as an array with 1 item.
   - Exclude internal eWallet transfers (e.g. GO+ Cash Out, Quick Reload, transfer to own self). If it's a top-up, set is_expense: false, event: "Reload".
   - If no valid transactions are found, set is_valid: false.

2. FIELDS FOR EACH TRANSACTION:
   - is_expense: (boolean) true for payment/debit, false for income/reload.
   - date: Format STRICTLY as "D-Mmm-YYYY" (e.g. "10-Oct-2026", "9-Oct-2026"). If year is missing, use "2026".
   - amount: Exact numeric float value in MYR (e.g. 12.50, 8.00).
   - type: Must be EXACTLY one of: "E Wallet", "Maybank", "RHB", "Cash", "PMO".
   - event: Must be EXACTLY one of:
     * "Meal": food, drinks, restaurants, mixed rice, cafes, mamak, foodpanda, grabfood
     * "Grocery": supermarkets, convenience stores, KK Mart, 99 Speedmart, FamilyMart, Watson's, Guardian
     * "Transportation": LRT, MRT, petrol, toll/RFID, parking, grab car
     * "Subscription fee": Apple, Netflix, Spotify, cloud, recurring services
     * "Online Shopping": Shopee, Lazada, TikTok Shop, gadgets
     * "Entertainment": cinema, games, outings
     * "Electric & Water Bills": utilities, TNB, internet
     * "Rental": house/room rent
     * "Transfer": money sent to friends/family
     * "Reload": balance reload
   - note: Clean Merchant or Payee name only (e.g. "Kim Seng Mixed Rice", "KK Mart", "Starbucks"). Max 35 chars.

OUTPUT STRICT JSON FORMAT ONLY:
{
  "is_valid": true,
  "transactions": [
    {
      "is_expense": true,
      "date": "10-Oct-2026",
      "amount": 12.50,
      "type": "E Wallet",
      "event": "Meal",
      "note": "Kim Seng Mixed Rice"
    }
  ],
  "summary": "Found 1 Meal transaction of RM 12.50"
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
                data = json.loads(cand)
                return data
        except Exception as e:
            last_err = e
            continue

    raise Exception(f"Gemini API error: {last_err}")

# Lightweight health server for Render / Cloud deployment
class HealthServer(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.end_headers()
        self.wfile.write(b"Takoo Finance Bot is online 24/7!\n")
    def log_message(self, format, *args):
        return

def start_health_server():
    port = int(os.environ.get("PORT", 8080))
    server = HTTPServer(("0.0.0.0", port), HealthServer)
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    print(f"Health server running on port {port}")

def run_bot_service():
    start_health_server()
    cfg = load_config()
    token = os.environ.get("TELEGRAM_BOT_TOKEN") or cfg.get("bot_token")
    if not token:
        print("Bot token missing in config.json or TELEGRAM_BOT_TOKEN env")
        return

    print("Takoo Finance Bot started. Polling Telegram for updates...")
    last_update_id = 0

    try:
        cmd_url = f"https://api.telegram.org/bot{token}/setMyCommands"
        cmds = {
            "commands": [
                {"command": "report", "description": "Spending trends & 10-sec daily report"},
                {"command": "balance", "description": "View current account balances"},
                {"command": "add", "description": "Insert a new transaction (/add or wizard)"},
                {"command": "recent", "description": "View recent transactions"},
                {"command": "set_gemini_key", "description": "Configure Gemini API key for receipts"},
                {"command": "help", "description": "Help and commands list"}
            ]
        }
        req = urllib.request.Request(cmd_url, data=json.dumps(cmds).encode('utf-8'), headers={"Content-Type": "application/json"})
        urllib.request.urlopen(req, timeout=10)
    except Exception as e:
        print("Failed to set commands menu:", e)

    while True:
        try:
            url = f"https://api.telegram.org/bot{token}/getUpdates?offset={last_update_id + 1}&timeout=30"
            with urllib.request.urlopen(url, timeout=35) as resp:
                data = json.load(resp)
                for update in data.get("result", []):
                    last_update_id = update["update_id"]

                    # 1. Handle Inline Keyboard Callbacks
                    if "callback_query" in update:
                        cb = update["callback_query"]
                        cb_id = cb["id"]
                        cb_data = cb.get("data", "")
                        cb_chat_id = cb["message"]["chat"]["id"]
                        cb_msg_id = cb["message"]["message_id"]

                        if cb_data.startswith("confirm:"):
                            confirm_id = cb_data.split(":", 1)[1]
                            tx_items = PENDING_CONFIRMATIONS.pop(confirm_id, None)
                            if tx_items:
                                answer_callback_query(token, cb_id, "Writing to Google Sheets...")
                                try:
                                    s_row, e_row = append_transactions_to_sheet(tx_items)
                                    row_text = f"Row `#{s_row}`" if s_row == e_row else f"Rows `#{s_row} to #{e_row}`"
                                    
                                    tot_amt = sum([float(t.get("debit") or 0) for t in tx_items])
                                    confirm_text = (
                                        f"✅ *{len(tx_items)} Transaction(s) Recorded!*\n\n"
                                        f"📍 *Location:* {row_text} in `2026 Oct Basic Acc 1`\n"
                                        f"💰 *Total Recorded:* `RM {tot_amt:.2f}`\n\n"
                                        f"Formula balances updated automatically. 🚀\n"
                                        f"[View Google Sheet]({SHEET_URL})"
                                    )
                                    edit_telegram_message(token, cb_chat_id, cb_msg_id, confirm_text, reply_markup=None)
                                except Exception as e:
                                    edit_telegram_message(token, cb_chat_id, cb_msg_id, f"❌ Failed to write to sheet: {e}")
                            else:
                                answer_callback_query(token, cb_id, "Transaction expired or already saved.")

                        elif cb_data.startswith("cancel:"):
                            confirm_id = cb_data.split(":", 1)[1]
                            PENDING_CONFIRMATIONS.pop(confirm_id, None)
                            answer_callback_query(token, cb_id, "Cancelled")
                            edit_telegram_message(token, cb_chat_id, cb_msg_id, "❌ *Transactions cancelled.*")

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
                                         {"text": "🏛️ RHB", "callback_data": "wiz_acc:RHB"}],
                                        [{"text": "📈 PMO", "callback_data": "wiz_acc:PMO"}]
                                    ]
                                }
                                edit_telegram_message(token, cb_chat_id, cb_msg_id, f"Category: *{cat}*\n\n💳 Select Payment Account:", reply_markup=acc_kb)

                        elif cb_data.startswith("wiz_acc:"):
                            acc = cb_data.split(":", 1)[1]
                            sess = WIZARD_SESSIONS.get(cb_chat_id)
                            if sess:
                                sess["type"] = acc
                                sess["step"] = "note"
                                answer_callback_query(token, cb_id)
                                edit_telegram_message(token, cb_chat_id, cb_msg_id,
                                    f"Category: *{sess['event']}*\nAccount: *{acc}*\n\n"
                                    "✍️ Reply with merchant / note description (e.g. `Kim Seng Mixed Rice`, or reply `skip`):"
                                )
                        continue

                    msg = update.get("message", {})
                    chat_id = msg.get("chat", {}).get("id")
                    text = msg.get("text", "").strip()

                    if not chat_id:
                        continue

                    # 2. Handle Photo Upload (Receipt or Statement Screenshot)
                    if "photo" in msg:
                        send_telegram_message(token, chat_id, "🔍 Analyzing screenshot with Gemini Vision AI...")
                        cfg = load_config()
                        g_key = os.environ.get("GEMINI_API_KEY") or cfg.get("gemini_api_key")

                        if not g_key:
                            send_telegram_message(token, chat_id, (
                                "🔑 *Gemini API Key Required*\n\n"
                                "To automatically extract transactions from receipts, please set your Gemini API key.\n\n"
                                "Command:\n`/set_gemini_key YOUR_GEMINI_API_KEY`\n\n"
                                "_(Get a free API key at [Google AI Studio](https://aistudio.google.com/))_"
                            ))
                            continue

                        try:
                            file_id = msg["photo"][-1]["file_id"]
                            img_bytes = download_telegram_photo(token, file_id)
                            parsed = parse_receipt_with_gemini(img_bytes, g_key)

                            if not parsed.get("is_valid"):
                                reason = parsed.get("reason", "Could not identify financial transactions in this screenshot.")
                                send_telegram_message(token, chat_id, f"⚠️ *Not Recorded:* {reason}")
                                continue

                            tx_list = parsed.get("transactions", [])
                            if not tx_list and "amount" in parsed:
                                # Backward compatibility for single object
                                tx_list = [parsed]

                            if not tx_list:
                                send_telegram_message(token, chat_id, "⚠️ No valid transactions found in this image.")
                                continue

                            c_id = str(uuid.uuid4())[:8]
                            to_record = []
                            preview_lines = []
                            total_debit = 0.0

                            for idx, tx in enumerate(tx_list, 1):
                                amt = float(tx.get("amount", 0))
                                is_exp = tx.get("is_expense", True)
                                if is_exp:
                                    total_debit += amt
                                amt_str = f"-RM {amt:.2f}" if is_exp else f"+RM {amt:.2f}"
                                
                                to_record.append({
                                    "date": tx.get("date", datetime.now().strftime("%-d-%b-%Y")),
                                    "credit": "" if is_exp else amt,
                                    "debit": amt if is_exp else "",
                                    "type": tx.get("type", "E Wallet"),
                                    "event": tx.get("event", "Meal"),
                                    "note": tx.get("note", "")
                                })
                                preview_lines.append(f"{idx}. *{tx.get('event')}*: `{amt_str}`\n   _{tx.get('note') or '-'} • {tx.get('type')} • {tx.get('date')}_")

                            PENDING_CONFIRMATIONS[c_id] = to_record

                            if len(to_record) == 1:
                                card_header = "🧾 *Receipt Extracted (1 Transaction):*"
                            else:
                                card_header = f"🧾 *Found {len(to_record)} Transactions in Screenshot:*"

                            card_text = (
                                f"{card_header}\n\n"
                                + "\n".join(preview_lines) + "\n\n"
                                f"💰 *Total Debit:* `RM {total_debit:.2f}`\n\n"
                                f"Confirm adding to Google Sheet?"
                            )

                            kb = {
                                "inline_keyboard": [[
                                    {"text": f"✅ Confirm & Add All ({len(to_record)})", "callback_data": f"confirm:{c_id}"},
                                    {"text": "❌ Cancel", "callback_data": f"cancel:{c_id}"}
                                ]]
                            }
                            send_telegram_message(token, chat_id, card_text, reply_markup=kb)

                        except Exception as e:
                            send_telegram_message(token, chat_id, f"❌ Failed to analyze receipt: {e}")
                        continue

                    # 3. Handle Active Wizard Steps
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
                                         {"text": "⚡ Bills", "callback_data": "wiz_cat:Electric & Water Bills"}],
                                        [{"text": "🔄 Transfer", "callback_data": "wiz_cat:Transfer"},
                                         {"text": "➕ Reload", "callback_data": "wiz_cat:Reload"}]
                                    ]
                                }
                                send_telegram_message(token, chat_id, f"Amount: `RM {amt:.2f}`\n\n🏷️ Select Category:", reply_markup=cat_kb)
                            except:
                                send_telegram_message(token, chat_id, "⚠️ Invalid amount. Please enter numbers like `12.50`:")
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
                                "📋 *Confirm Transaction Insertion:*\n\n"
                                f"📅 *Date:* `{today_str}`\n"
                                f"💸 *Debit:* `RM {sess['amount']:.2f}`\n"
                                f"💳 *Account:* `{sess.get('type')}`\n"
                                f"🏷️ *Category:* `{sess.get('event')}`\n"
                                f"📝 *Note:* `{note_val or '-'}`\n\n"
                                "Add to Google Sheet?"
                            )
                            kb = {
                                "inline_keyboard": [[
                                    {"text": "✅ Confirm & Add", "callback_data": f"confirm:{c_id}"},
                                    {"text": "❌ Cancel", "callback_data": f"cancel:{c_id}"}
                                ]]
                            }
                            send_telegram_message(token, chat_id, summary, reply_markup=kb)
                            continue

                    # 4. Handle Text Commands
                    if text.startswith("/set_gemini_key"):
                        parts = text.split(maxsplit=1)
                        if len(parts) > 1:
                            new_key = parts[1].strip()
                            cfg = load_config()
                            cfg["gemini_api_key"] = new_key
                            save_config(cfg)
                            send_telegram_message(token, chat_id, "✅ *Gemini API Key configured!* You can now send receipt screenshots directly to this chat.")
                        else:
                            send_telegram_message(token, chat_id, "Usage:\n`/set_gemini_key YOUR_GEMINI_KEY`")

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
                                    "📋 *Confirm Quick Transaction:*\n\n"
                                    f"📅 *Date:* `{today_str}`\n"
                                    f"💸 *Debit:* `RM {amt:.2f}`\n"
                                    f"💳 *Account:* `{acc}`\n"
                                    f"🏷️ *Category:* `{cat}`\n"
                                    f"📝 *Note:* `{note or '-'}`"
                                )
                                kb = {
                                    "inline_keyboard": [[
                                        {"text": "✅ Confirm & Add", "callback_data": f"confirm:{c_id}"},
                                        {"text": "❌ Cancel", "callback_data": f"cancel:{c_id}"}
                                    ]]
                                }
                                send_telegram_message(token, chat_id, summary, reply_markup=kb)
                            except Exception as e:
                                send_telegram_message(token, chat_id, f"⚠️ Error: {e}\nFormat: `/add 12.50 Meal E-Wallet Kim Seng`")
                        else:
                            WIZARD_SESSIONS[chat_id] = {"step": "amount"}
                            send_telegram_message(token, chat_id, "💰 *Enter amount in RM:* (e.g. `12.50`)")

                    elif text.startswith("/start") or text.startswith("/help"):
                        help_text = (
                            "👋 *Welcome to Takoo Finance Bot!*\n\n"
                            "I track your daily spending trends and help you record transactions into Google Sheets (`记账表`).\n\n"
                            "🌟 *Ways to Add Transactions:*\n"
                            "1. 📸 *Send a screenshot/photo* of 1 or multiple transactions (powered by Gemini AI).\n"
                            "2. ✍️ *Command:* `/add <amount> <category> <note>` (e.g. `/add 8.00 Meal Kim Seng Mixed Rice`)\n"
                            "3. 🪄 *Interactive Wizard:* Type `/add` to use step-by-step buttons.\n\n"
                            "📊 *Tracking Commands:*\n"
                            "• `/report` - Today's spending trends (10-second summary)\n"
                            "• `/balance` - Account balances snapshot\n"
                            "• `/recent` - Last 10 transactions\n"
                            "• `/set_gemini_key` - Configure Google Gemini API key\n"
                            "• `/help` - Show this guide"
                        )
                        send_telegram_message(token, chat_id, help_text)

                    elif text.startswith("/report") or text.startswith("/today"):
                        f_data = fetch_latest_finance_data()
                        if f_data:
                            rep = format_daily_report(f_data)
                            send_telegram_message(token, chat_id, rep)
                        else:
                            send_telegram_message(token, chat_id, "⚠️ Failed to fetch data from Google Sheets.")

                    elif text.startswith("/balance"):
                        f_data = fetch_latest_finance_data()
                        if f_data:
                            bal = format_balances(f_data)
                            send_telegram_message(token, chat_id, bal)
                        else:
                            send_telegram_message(token, chat_id, "⚠️ Failed to fetch balance.")

                    elif text.startswith("/recent"):
                        f_data = fetch_latest_finance_data()
                        if f_data:
                            rc = format_recent(f_data)
                            send_telegram_message(token, chat_id, rc)
                        else:
                            send_telegram_message(token, chat_id, "⚠️ Failed to fetch transactions.")

        except Exception as e:
            time.sleep(2)

if __name__ == "__main__":
    run_bot_service()
