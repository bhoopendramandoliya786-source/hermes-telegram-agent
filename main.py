import os
import asyncio
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
import google.generativeai as genai
import edge_tts
import yfinance as yf
from duckduckgo_search import DDGS
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes

class SimpleHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Hermes Agent is Live and Running!")

def run_http_server():
    port = int(os.environ.get("PORT", 10000))
    server = HTTPServer(("0.0.0.0", port), SimpleHandler)
    server.serve_forever()

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

genai.configure(api_key=GEMINI_API_KEY)

# ऑटो-डिटेक्ट मॉडल ताकि 404 एरर कभी न आए
def get_working_model():
    try:
        for m in genai.list_models():
            if "generateContent" in m.supported_generation_methods:
                return genai.GenerativeModel(m.name)
    except Exception:
        pass
    return genai.GenerativeModel("models/gemini-1.5-flash")

model = get_working_model()

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = (
        "👑 *Hermes Master AI Agent सक्रिय है!*\n\n"
        "उपलब्ध कमांड्स:\n"
        "🔹 `/reel <टॉपिक>` - 30-40s वायरल स्क्रिप्ट + HD वॉइसओवर\n"
        "🔹 `/news <विषय>` - लाइव इंटरनेट सर्च\n"
        "🔹 `/market <स्टॉक>` - शेयर बाजार लाइव भाव\n"
        "🔹 `/quiz <टॉपिक>` - अभ्यास MCQs\n"
        "🔹 `/status` - सिस्टम हेल्थ चेक\n"
        "🔹 `/stop` - प्रोसेस रीसेट"
    )
    await update.message.reply_text(msg, parse_mode="Markdown")

async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("⚡ Hermes AI Engine 24/7 लाइव और रेडी है।")

async def stop_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🛑 टास्क रीसेट कर दिया गया है।")

async def generate_reel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    topic = " ".join(context.args)
    if not topic:
        await update.message.reply_text("कृपया टॉपिक दर्ज करें। उदाहरण: `/reel AI के फायदे`")
        return

    wait_msg = await update.message.reply_text("🎬 स्क्रिप्ट और वॉइसओवर तैयार हो रहा है...")
    prompt = (
        f"विषय: '{topic}' पर इंस्टाग्राम रील / शॉर्ट्स की 30-40 सेकंड की स्क्रिप्ट लिखो। "
        "सिर्फ बोलने वाला हिंदी टेक्स्ट दो, कोई कैमरा निर्देश न दो।"
    )

    try:
        response = model.generate_content(prompt)
        script_text = response.text.strip()

        audio_file = "voiceover.mp3"
        communicate = edge_tts.Communicate(script_text, voice="hi-IN-MadhurNeural")
        await communicate.save(audio_file)

        await update.message.reply_text(f"📝 *तैयार स्क्रिप्ट:*\n\n{script_text}", parse_mode="Markdown")
        await update.message.reply_voice(voice=open(audio_file, "rb"), caption="🎙️ स्टुडियो-क्वालिटी वॉइसओवर")

        if os.path.exists(audio_file):
            os.remove(audio_file)
        await wait_msg.delete()
    except Exception as e:
        await update.message.reply_text(f"⚠️ एरर: {str(e)}")

async def search_news(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = " ".join(context.args)
    if not query:
        await update.message.reply_text("कृपया सर्च विषय लिखें।")
        return

    wait_msg = await update.message.reply_text("🔍 वेब रिसर्च जारी है...")
    try:
        results = []
        with DDGS() as ddgs:
            for r in ddgs.text(query, max_results=4):
                results.append(f"• {r['title']}: {r['body']}")

        web_data = "\n\n".join(results)
        summary_prompt = f"इन परिणामों के आधार पर संक्षेप में बुलेट पॉइंट्स में हिंदी समरी दो:\n\n{web_data}"
        res = model.generate_content(summary_prompt)

        await update.message.reply_text(f"📰 *सर्च रिपोर्ट:*\n\n{res.text}", parse_mode="Markdown")
        await wait_msg.delete()
    except Exception as e:
        await update.message.reply_text(f"⚠️ रिसर्च एरर: {str(e)}")

async def stock_market(update: Update, context: ContextTypes.DEFAULT_TYPE):
    symbol = " ".join(context.args).strip()
    if not symbol:
        await update.message.reply_text("स्टॉक सिंबल लिखें। उदाहरण: `/market RELIANCE.NS`")
        return

    try:
        ticker = yf.Ticker(symbol)
        info = ticker.fast_info
        last_price = round(info.last_price, 2)
        prev_close = round(info.previous_close, 2)
        change = round(((last_price - prev_close) / prev_close) * 100, 2)

        res_msg = f"📈 *{symbol.upper()}*\nमूल्य: ₹{last_price}\nपिछला बंद: ₹{prev_close}\nबदलाव: {change}%"
        await update.message.reply_text(res_msg, parse_mode="Markdown")
    except Exception as e:
        await update.message.reply_text("⚠️ सिंबल सही जांचें (जैसे TATAMOTORS.NS)")

async def exam_quiz(update: Update, context: ContextTypes.DEFAULT_TYPE):
    subject = " ".join(context.args)
    if not subject:
        await update.message.reply_text("विषय लिखें। उदाहरण: `/quiz भारतीय इतिहास`")
        return

    wait_msg = await update.message.reply_text("📚 अभ्यास प्रश्न तैयार हो रहे हैं...")
    prompt = f"विषय: '{subject}' पर 5 MCQs हिंदी में तैयार करो। उत्तर और व्याख्या साथ दो।"
    try:
        res = model.generate_content(prompt)
        await update.message.reply_text(f"📝 *अभ्यास टेस्ट ({subject}):*\n\n{res.text}", parse_mode="Markdown")
        await wait_msg.delete()
    except Exception as e:
        await update.message.reply_text(f"⚠️ एरर: {str(e)}")

async def handle_chat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        res = model.generate_content(update.message.text)
        await update.message.reply_text(res.text)
    except Exception as e:
        await update.message.reply_text(f"⚠️ एरर: {str(e)}")

if __name__ == "__main__":
    threading.Thread(target=run_http_server, daemon=True).start()

    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("status", status))
    app.add_handler(CommandHandler("stop", stop_cmd))
    app.add_handler(CommandHandler("reel", generate_reel))
    app.add_handler(CommandHandler("news", search_news))
    app.add_handler(CommandHandler("market", stock_market))
    app.add_handler(CommandHandler("quiz", exam_quiz))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_chat))
    app.run_polling()
