import urllib.request, json, time, os, sys

sys.path.append(os.path.dirname(os.path.abspath(__file__)))
import bot

token = "8365471050:AAGXHCBfJkXVhh1HHigyBU0zXUqQaOLjhJw"
print("Waiting for /start message on @takoo_helper_bot...")

start_time = time.time()
while time.time() - start_time < 300: # 5 min timeout
    try:
        url = f"https://api.telegram.org/bot{token}/getUpdates?timeout=10"
        with urllib.request.urlopen(url, timeout=15) as resp:
            data = json.load(resp)
            results = data.get("result", [])
            if results:
                last_update = results[-1]
                msg = last_update.get("message", {})
                chat = msg.get("chat", {})
                chat_id = chat.get("id")
                first_name = chat.get("first_name", "there")
                if chat_id:
                    print(f"FOUND CHAT ID: {chat_id} from {first_name}!")
                    cfg = bot.load_config()
                    cfg["chat_id"] = chat_id
                    bot.save_config(cfg)
                    
                    # Send welcome message and live report
                    finance_data = bot.fetch_latest_finance_data()
                    report_text = bot.format_daily_report(finance_data)
                    welcome = f"👋 Hello {first_name}!\n\nYour *Takoo Finance Bot* is now connected to your Google Sheet (`记账表`)!\n\nHere is your live balance summary:\n\n{report_text}"
                    bot.send_telegram_message(token, chat_id, welcome)
                    print("Welcome report delivered successfully!")
                    sys.exit(0)
    except Exception as e:
        print("Polling error:", e)
    time.sleep(2)

print("Listener timed out.")
