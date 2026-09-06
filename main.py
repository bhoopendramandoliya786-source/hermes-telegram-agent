import os
import gc
import re
import json
import time
import threading
import requests
from http.server import HTTPServer, BaseHTTPRequestHandler
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

class SimpleHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Hermes Cloud Engine Running")

def run_http_server():
    port = int(os.environ.get("PORT", 10000))
    server = HTTPServer(("0.0.0.0", port), SimpleHandler)
    server.serve_forever()

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
CREATOMATE_API_KEY = os.getenv("CREATOMATE_API_KEY")

def clean_text(text):
    text = re.sub(r'[*_~`#\[\]\(\)\<\>\"\'\\]', ' ', text)
    return re.sub(r'\s+', ' ', text).strip()

def clean_user_prompt(text):
    t = clean_text(text)
    t = re.sub(r'(पर वीडियो बनाओ|वीडियो बनाओ|के बारे में बताओ|अच्छे से विजुअल|वीडियो बनाइए|रील बनाओ)', '', t, flags=re.IGNORECASE)
    return t.strip() or text.strip()

def generate_script_safe(raw_topic):
    topic = clean_user_prompt(raw_topic)
    if GEMINI_API_KEY:
        headers = {
            "Content-Type": "application/json",
            "x-goog-api-key": GEMINI_API_KEY
        }
        prompt = f"""
Create a 3-scene Hindi Reel script about: '{topic}'.
Return ONLY JSON:
{{
  "scenes": [
    {{"speech": "पहला वाक्य हिंदी में", "visual_prompt": "cinematic hyperrealistic 8k visual of {topic}"}},
    {{"speech": "दूसरा वाक्य हिंदी में", "visual_prompt": "cinematic detailed visual of {topic}"}},
    {{"speech": "तीसरा वाक्य हिंदी में", "visual_prompt": "epic atmospheric visual of {topic}"}}
  ]
}}
"""
        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": 0.4, "response_mime_type": "application/json"}
        }
        try:
            url = "https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent"
            res = requests.post(url, headers=headers, json=payload, timeout=10)
            if res.status_code == 200:
                data = res.json()
                out_text = data['candidates'][0]['content']['parts'][0]['text']
                match = re.search(r'\{.*\}', out_text, re.DOTALL)
                if match:
                    parsed = json.loads(match.group(0))
                    if "scenes" in parsed and len(parsed["scenes"]) >= 3:
                        return parsed["scenes"]
        except Exception:
            pass

    en = re.sub(r'[^a-zA-Z0-9\s]', '', topic).strip() or "epic facts"
    return [
        {"speech": f"क्या आप जानते हैं {topic} के बारे में यह चौंकाने वाला सच?", "visual_prompt": f"cinematic portrait view of {en}, 8k"},
        {"speech": f"इसके पीछे की सच्चाई जानकर आपके होश उड़ जाएंगे।", "visual_prompt": f"detailed dynamic shot of {en}, dramatic"},
        {"speech": "ऐसी ही अद्भुत जानकारियों के लिए हमें अभी फॉलो करें।", "visual_prompt": f"epic majestic atmospheric view of {en}"}
    ]

def render_with_creatomate(scenes):
    elements = []
    current_time = 0.0
    scene_duration = 4.0  # हर सीन 4 सेकंड

    for sc in scenes:
        prompt_encoded = requests.utils.quote(sc["visual_prompt"] + ", vertical 9:16, cinematic, photorealistic, 8k")
        img_url = f"https://image.pollinations.ai/prompt/{prompt_encoded}?width=1080&height=1920&nologo=true&model=turbo"

        # 1. बैकग्राउंड इमेज + स्मूथ पैन-ज़ूम इफ़ेक्ट
        elements.append({
            "type": "image",
            "url": img_url,
            "time": current_time,
            "duration": scene_duration,
            "fit": "cover",
            "animations": [
                {
                    "time": "start",
                    "duration": scene_duration,
                    "easing": "linear",
                    "type": "scale",
                    "scale_start": "100%",
                    "scale_end": "115%"
                }
            ]
        })

        # 2. ऑटोमैटिक टेक्स्ट-टू-स्पीच वॉइस (हिंदी)
        elements.append({
            "type": "audio",
            "source": "text-to-speech",
            "voice": "hi-IN-MadhurNeural",
            "text": sc["speech"],
            "time": current_time
        })

        # 3. बोल्ड इंस्टाग्राम सबटाइटल्स
        elements.append({
            "type": "text",
            "text": sc["speech"],
            "time": current_time,
            "duration": scene_duration,
            "y": "72%",
            "width": "85%",
            "font_family": "Noto Sans Devanagari",
            "font_size": "56 px",
            "font_weight": "bold",
            "fill_color": "#FFE600",
            "stroke_color": "#000000",
            "stroke_width": "8 px",
            "x_alignment": "50%",
            "y_alignment": "50%"
        })

        current_time += scene_duration

    # Creatomate Cloud Render API कॉल
    headers = {
        "Authorization": f"Bearer {CREATOMATE_API_KEY}",
        "Content-Type": "application/json"
    }

    render_payload = {
        "output_format": "mp4",
        "frame_rate": 60,
        "width": 1080,
        "height": 1920,
        "elements": elements
    }

    res = requests.post("https://api.creatomate.com/v1/renders", headers=headers, json=render_payload, timeout=20)
    if res.status_code not in (200, 202):
        raise Exception(f"Creatomate Error: {res.text}")

    render_data = res.json()[0]
    render_id = render_data["id"]

    # रेंडर पूरा होने का इंतज़ार (क्लाउड पोलिंग)
    for _ in range(30):
        time.sleep(2)
        check = requests.get(f"https://api.creatomate.com/v1/renders/{render_id}", headers=headers, timeout=10)
        status_info = check.json()
        if status_info.get("status") == "succeeded":
            return status_info.get("url")
        elif status_info.get("status") == "failed":
            raise Exception("Cloud render failed.")

    raise Exception("रेंडर में अधिक समय लग रहा है।")

async def generate_reel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    topic = clean_text(" ".join(context.args))
    if not topic:
        await update.message.reply_text("कृपया विषय लिखें। उदाहरण: `/reel ब्लैक होल का रहस्य`")
        return

    wait_msg = await update.message.reply_text(f"🚀 '{topic}' पर 60 FPS क्लाउड रील तैयार हो रही है (10-15 सेकंड)...")
    try:
        scenes = generate_script_safe(topic)
        script_text = "\n\n".join([s["speech"] for s in scenes])
        await update.message.reply_text(f"📝 *स्क्रिप्ट:*\n\n{script_text}", parse_mode="Markdown")

        video_url = render_with_creatomate(scenes)
        await update.message.reply_video(video=video_url, caption=f"🔥 60 FPS 1080p रील: {topic}")

    except Exception as e:
        await update.message.reply_text(f"⚠️ एरर: {str(e)}")
    finally:
        gc.collect()
        try:
            await wait_msg.delete()
        except Exception:
            pass

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("👑 Hermes 60FPS Cloud Studio सक्रिय है!\n\nरील बनाने के लिए भेजें:\n`/reel <टॉपिक>`")

async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("✅ Hermes Cloud Engine 100% एक्टिव है!")

if __name__ == "__main__":
    threading.Thread(target=run_http_server, daemon=True).start()
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("status", status))
    app.add_handler(CommandHandler("reel", generate_reel))
    app.run_polling()
