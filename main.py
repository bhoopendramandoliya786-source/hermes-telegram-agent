import os
import asyncio
import google.generativeai as genai
import edge_tts
import yfinance as yf
from duckduckgo_search import DDGS
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel("gemini-1.5-flash")

# 1. Start Command
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = (
        "👑 *Hermes Master AI Agent सक्रिय है!*\n\n"
        "उपलब्ध कमांड्स:\n"
        "🔹 `/reel <टॉपिक>` - 30-40s वायरल स्क्रिप्ट + HD वॉइसओवर तैयार करें\n"
        "🔹 `/news <विषय>` - लाइव इंटरनेट सर्च और ट्रेंडिंग रिसर्च\n"
        "🔹 `/market <स्टॉक>` - शेयर बाजार लाइव भाव व ओवरव्यू (उदा. /market TATAMOTORS.NS)\n"
        "🔹 `/quiz <टॉपिक>` - 5 कठिन अभ्यास MCQs उत्तर और व्याख्या सहित\n"
        "🔹 `/status` - सिस्टम हेल्थ चेक\n"
        "🔹 `/stop` - वर्तमान प्रोसेस रीसेट करें\n\n"
        "या आप सीधे कोई भी सवाल पूछ सकते हैं!"
    )
    await update.message.reply_text(msg, parse_mode="Markdown")

# 2. Status & Stop
async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("⚡ Hermes AI Engine 24/7 लाइव और रेडी है।")

async def stop_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🛑 टास्क रीसेट कर दिया गया है।")

# 3. Reel & Shorts Automation
async def generate_reel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    topic = " ".join(context.args)
    if not topic:
        await update.message.reply_text("कृपया टॉपिक दर्ज करें।\nउदाहरण: `/reel AI से पैसे कमाने के 3 तरीके`", parse_mode="Markdown")
        return

    wait_msg = await update.message.reply_text("🎬 वायरल स्क्रिप्ट और वॉइसओवर तैयार किया जा रहा है...")

    prompt = (
        f"तुम एक टॉप-टियर वायरल वीडियो स्क्रिप्ट राइटर हो। विषय: '{topic}'। "
        "इंस्टाग्राम रील और यूट्यूब शॉर्ट्स के लिए 30-40 सेकंड की ऐसी स्क्रिप्ट लिखो जो शुरू के 3 सेकंड में हुक करे। "
        "सिर्फ साफ हिंदी टेक्स्ट लिखो जो सीधा बोला जाएगा। कोई ब्रैकेट, इमोजी या कैमरा डायरेक्शन न लिखो।"
    )

    try:
        response = model.generate_content(prompt)
        script_text = response.text.strip()

        audio_file = "voiceover.mp3"
        communicate = edge_tts.Communicate(script_text, voice="hi-IN-MadhurNeural")
        await communicate.save(audio_file)

        await update.message.reply_text(f"📝 *तैयार स्क्रिप्ट:*\n\n{script_text}", parse_mode="Markdown")
        await update.message.reply_voice(voice=open(audio_file, "rb"), caption="🎙️ स्टुडियो-क्वालिटी वॉइसओवर (फ्री Edge TTS)")

        if os.path.exists(audio_file):
            os.remove(audio_file)
        await wait_msg.delete()

    except Exception as e:
        await update.message.reply_text(f"⚠️ एरर: {str(e)}")

# 4. Live Web Research
async def search_news(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = " ".join(context.args)
    if not query:
        await update.message.reply_text("कृपया सर्च विषय लिखें। उदाहरण: `/news AI latest trends`")
        return

    wait_msg = await update.message.reply_text("🔍 वेब रिसर्च जारी है...")
    try:
        results = []
        with DDGS() as ddgs:
            for r in ddgs.text(query, max_results=4):
                results.append(f"• {r['title']}: {r['body']}")

        web_data = "\n\n".join(results)
        summary_prompt = f"इन खोज परिणामों के आधार पर संक्षेप में 4-5 बुलेट पॉइंट्स में हिंदी में समरी दो:\n\n{web_data}"
        res = model.generate_content(summary_prompt)

        await update.message.reply_text(f"📰 *सर्च रिपोर्ट:*\n\n{res.text}", parse_mode="Markdown")
        await wait_msg.delete()
    except Exception as e:
        await update.message.reply_text(f"⚠️ रिसर्च एरर: {str(e)}")

# 5. Stock Market Check
async def stock_market(update: Update, context: ContextTypes.DEFAULT_TYPE):
    symbol = " ".join(context.args).strip()
    if not symbol:
        await update.message.reply_text("स्टॉक सिंबल लिखें। उदाहरण: `/market RELIANCE.NS` या `/market INFY.NS`")
        return

    try:
        ticker = yf.Ticker(symbol)
        info = ticker.fast_info
        last_price = info.last_price
        prev_close = info.previous_close
        change = round(((last_price - prev_close) / prev_close) * 100, 2)

        res_msg = (
            f"📈 *स्टॉक विवरण: {symbol.upper()}*\n"
            f"वर्तमान मूल्य: ₹{round(last_price, 2)}\n"
            f"पिछला बंद: ₹{round(prev_close, 2)}\n"
            f"बदलाव: {change}%"
        )
        await update.message.reply_text(res_msg, parse_mode="Markdown")
    except Exception as e:
        await update.message.reply_text(f"⚠️ डेटा निकालने में समस्या: सिंबल सही जांचें (जैसे TATAMOTORS.NS)")

# 6. Study / Mock Quiz Generator
async def exam_quiz(update: Update, context: ContextTypes.DEFAULT_TYPE):
    subject = " ".join(context.args)
    if not subject:
        await update.message.reply_text("विषय लिखें। उदाहरण: `/quiz भारतीय संविधान`")
        return

    wait_msg = await update.message.reply_text("📚 अभ्यास प्रश्न तैयार किए जा रहे हैं...")
    prompt = (
        f"विषय: '{subject}' से संबंधित 5 उच्च-स्तरीय बहुविकल्पीय प्रश्न (MCQs) हिंदी में तैयार करो। "
        "हर प्रश्न के 4 विकल्प (A, B, C, D) दो, और नीचे सही उत्तर तथा 2 लाइन में स्पष्ट कारण लिखो।"
    )
    try:
        res = model.generate_content(prompt)
        await update.message.reply_text(f"📝 *अभ्यास टेस्ट ({subject}):*\n\n{res.text}", parse_mode="Markdown")
        await wait_msg.delete()
    except Exception as e:
        await update.message.reply_text(f"⚠️ एरर: {str(e)}")

# 7. General AI Chat
async def handle_chat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_text = update.message.text
    try:
        res = model.generate_content(user_text)
        await update.message.reply_text(res.text)
    except Exception as e:
        await update.message.reply_text(f"⚠️ एरर: {str(e)}")

if __name__ == "__main__":
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
