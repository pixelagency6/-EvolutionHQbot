import os
import html
import logging
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

from openai import AsyncOpenAI
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler, CallbackQueryHandler,
    ContextTypes, filters,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger("bot")

DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY")
ai = AsyncOpenAI(api_key=DEEPSEEK_API_KEY, base_url="https://api.deepseek.com") if DEEPSEEK_API_KEY else None
MODEL = "deepseek-chat"

MAX_INPUT = 4000

MODE_INSTR = {
    "correct": ("Correct all grammar, spelling and punctuation mistakes in the text. "
                "Return ONLY the corrected text, nothing else. Keep the original meaning and tone."),
    "explain": ("List the grammar, spelling and punctuation corrections for this text as short "
                "bullet points. Format each as: original → corrected (short reason). Plain text only."),
    "improve": ("Rewrite this text to be clearer, smoother and more professional while keeping the "
                "meaning and language. Return ONLY the improved text."),
}
MODE_LABEL = {"correct": "✅ Corrected", "explain": "📋 What changed", "improve": "✍️ Improve"}

# ============================================================
# Health server
# ============================================================
class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200); self.send_header("Content-Type", "text/plain"); self.end_headers()
        self.wfile.write(b"Grammar Bot alive.")
    def do_HEAD(self):
        self.send_response(200); self.send_header("Content-Type", "text/plain"); self.end_headers()
    def log_message(self, format, *args):
        return

def run_health_server():
    port = int(os.environ.get("PORT", 10000))
    HTTPServer(("0.0.0.0", port), HealthHandler).serve_forever()

# ============================================================
# Grammar processing
# ============================================================
async def process(text: str, mode: str) -> str:
    if not ai:
        return None
    instr = MODE_INSTR.get(mode, MODE_INSTR["correct"])
    try:
        r = await ai.chat.completions.create(
            model=MODEL,
            messages=[
                {"role": "system", "content": "You are a precise writing assistant. Output plain text only, no markdown symbols."},
                {"role": "user", "content": f"{instr}\n\nTEXT:\n{text}"},
            ],
            temperature=0.2, max_tokens=900,
        )
        return r.choices[0].message.content.strip()
    except Exception as e:
        log.error(f"process failed: {e}")
        return None

def mode_kb(current):
    row = [InlineKeyboardButton(("• " if k == current else "") + MODE_LABEL[k], callback_data=f"gr:{k}")
           for k in ("correct", "explain", "improve")]
    return InlineKeyboardMarkup([row])

async def send_result(target, context, mode):
    src = context.user_data.get("src")
    if not src:
        await target.reply_text("Send me some text first.")
        return
    result = await process(src, mode)
    if not result:
        await target.reply_text("❌ Couldn't process right now. Please try again.")
        return
    text = f"<b>{MODE_LABEL[mode]}:</b>\n\n{html.escape(result)}"
    await target.reply_text(text, parse_mode="HTML", reply_markup=mode_kb(mode))

# ============================================================
# Handlers
# ============================================================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "✍️ *Grammar & Spell Checker*\n\n"
        "Send me any text and I'll fix the grammar, spelling and punctuation. "
        "Then tap a button to see what changed or get a clearer, more professional rewrite.\n\n"
        "Paste your text below 👇",
        parse_mode="Markdown",
    )

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (update.message.text or "").strip()
    if len(text) < 2:
        return
    if len(text) > MAX_INPUT:
        text = text[:MAX_INPUT]
        await update.message.reply_text("ℹ️ Text was long — checking the first part.")
    context.user_data["src"] = text
    status = await update.message.reply_text("⏳ Checking…")
    await send_result(update.message, context, "correct")
    try:
        await status.delete()
    except Exception:
        pass

async def mode_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer("Working…")
    mode = q.data.split(":", 1)[1]
    await send_result(q.message, context, mode)

# ============================================================
# Main
# ============================================================
def main():
    token = os.environ.get("BOT_TOKEN")
    if not token:
        log.critical("BOT_TOKEN env var missing!")
        return
    if not ai:
        log.warning("No DEEPSEEK_API_KEY set — corrections will fail.")

    threading.Thread(target=run_health_server, daemon=True).start()

    app = Application.builder().token(token).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(mode_callback, pattern=r"^gr:"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    log.info("Grammar Bot is running...")
    app.run_polling()

if __name__ == "__main__":
    main()
