import os
import asyncio
import threading
import requests
import random
from http.server import HTTPServer, BaseHTTPRequestHandler
import google.generativeai as genai
import edge_tts
import yfinance as yf
from duckduckgo_search import DDGS
from moviepy.editor import VideoFileClip, AudioFileClip
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes

class SimpleHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Hermes Video Engine is Running!")

def run_http_server():
    port = int(os.environ.get("PORT", 10000))
    server = HTTPServer(("0.0.0.0", port), SimpleHandler)
    server.serve_forever()

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
PEXELS_API_KEY = os.getenv("PEXELS_API_KEY", "")

genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel("models/gemini-3.6-flash")

def download_vertical_video(query):
    if not PEXELS_API_KEY:
        return None
    headers = {"Authorization": PEXELS_API_KEY}
    url = f"https://api.pexels.com/videos/search?query={query}&orientation=portrait&per_page=6"
    
    try:
        res = requests.get(url, headers=headers).json()
        videos = res.get("videos", [])
        if not videos:
            fallback_url = "https://api.pexels.com/videos/search?query=cinematic+nature&orientation=portrait&per_page=5"
            res = requests.get(fallback_url, headers=headers).json()
            videos = res.get("videos", [])
        
        if videos:
            selected_video = random.choice(videos)
            files = selected_video.get("video_files", [])
            portrait_files = [f for f in files if f.get("height", 0) > f.get("width", 0)]
            target = portrait_files[0] if portrait_files else files[0]
            
            v_data = requests.get(target["link"], stream=True)
            bg_path = "bg_clip.mp4"
            with open(bg_path, "wb") as f:
                for chunk in v_data.iter_content(chunk_size=1024*1024):
                    f.write(chunk)
            return bg_path
    except Exception as e:
        print(f"Pexels fetch error: {e}")
    return None

async def generate_reel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    topic = " ".join(context.args)
    if not topic:
        await update.message.reply_text("कृपया विषय लिखें। उदाहरण: `/reel सफलता के नियम`")
        return

    status_msg = await update.message.reply_text("🎬 स्क्रिप्ट तैयार हो रही है और 9:16 HD वीडियो रेंडर हो रहा है...")
    prompt = (
        f"विषय: '{topic}' पर 25 से 30 सेकंड की एंगेजिंग रील स्क्रिप्ट लिखो। "
        "सिर्फ स्पष्ट हिंदी वाक्य दो, कोई कैमरा निर्देश या ब्रैकेट न हो।"
    )

    audio_file = "voiceover.mp3"
    final_video = "final_reel.mp4"
    bg_video = None

    try:
        response = model.generate_content(prompt)
        script_text = response.text.strip()

        comm = edge_tts.Communicate(script_text, voice="hi-IN-MadhurNeural")
        await comm.save(audio_file)

        bg_video = download_vertical_video(topic)

        if bg_video and os.path.exists(bg_video):
            a_clip = AudioFileClip(audio_file)
            v_clip = VideoFileClip(bg_video)

            if v_clip.duration < a_clip.duration:
                v_clip = v_clip.loop(duration=a_clip.duration)
            else:
                v_clip = v_clip.subclip(0, a_clip.duration)

            final = v_clip.set_audio(a_clip)
            final.write_videofile(
                final_video,
                codec="libx264",
                audio_codec="aac",
                fps=24,
                preset="ultrafast",
                logger=None
            )
            v_clip.close()
            a_clip.close()
            final.close()

            await update.message.reply_text(f"📝 *स्क्रिप्ट:*\n\n{script_text}", parse_mode="Markdown")
            with open(final_video, "rb") as vf:
                await update.message.reply_video(video=vf, caption=f"🔥 रील तैयार: {topic}")
        else:
            await update.message.reply_text(f"📝 *स्क्रिप्ट:*\n\n{script_text}", parse_mode="Markdown")
            with open(audio_file, "rb") as af:
                await update.message.reply_voice(voice=af, caption="🎙️ वॉइसओवर")

    except Exception as e:
        await update.message.reply_text(f"⚠️ एरर: {str(e)}")
    finally:
        for f in [audio_file, final_video, bg_video, "bg_clip.mp4"]:
            if f and os.path.exists(f):
                try:
                    os.remove(f)
                except Exception:
                    pass
        await status_msg.delete()

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

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = (
        "👑 *Hermes Master AI Agent सक्रिय है!*\n\n"
        "उपलब्ध कमांड्स:\n"
        "🔹 `/reel <टॉपिक>` - 9:16 HD वीडियो + वॉइसओवर तैयार करें\n"
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
