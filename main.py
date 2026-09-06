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
from google import genai
from google.genai import types

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

def generate_script_dynamic(raw_topic):
    topic = clean_user_prompt(raw_topic)
    
    if GEMINI_API_KEY:
        try:
            client = genai.Client(api_key=GEMINI_API_KEY)
            prompt = f"""
You are an expert viral content creator. Write an ultra-engaging, 3-scene Hindi YouTube Shorts/Reels script about: '{topic}'.

CRITICAL INSTRUCTIONS:
- DO NOT use generic template lines like 'क्या आप जानते हैं', 'इसके पीछे का रहस्य', or 'हैरान कर देने वाला सच'.
- Provide SPECIFIC facts, real history, interesting statistics, or deep trivia related directly to '{topic}'.
- Scene 1: An intense question or hook directly introducing '{topic}'.
- Scene 2: The most shocking, lesser-known reality or mechanism about '{topic}'.
- Scene 3: The surprising outcome, real-world impact, or mind-blowing conclusion about '{topic}'.

Return ONLY JSON matching this structure:
{{
  "scenes": [
    {{"speech": "पहला स्पेसिफिक वाक्य हिंदी में", "visual_prompt": "highly detailed English cinematic 8k visual prompt of {topic}"}},
    {{"speech": "दूसरा गहरा तथ्य हिंदी में", "visual_prompt": "highly detailed English cinematic visual showing the core mechanism"}},
    {{"speech": "तीसरा निष्कर्ष वाक्य हिंदी में", "visual_prompt": "epic cinematic dramatic visual conclusion"}}
  ]
}}
"""
            response = client.models.generate_content(
                model="gemini-2.5-flash",
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    temperature=0.7
                )
            )
            parsed = json.loads(response.text)
            if "scenes" in parsed and len(parsed["scenes"]) >= 3:
                return parsed["scenes"]
        except Exception as e:
            print(f"Gemini error: {e}")

    # केवल आपातकालीन बैकअप
    return [
        {"speech": f"{topic} की दुनिया में ऐसे कई राज़ छिपे हैं जो बहुत कम लोग समझ पाते हैं।", "visual_prompt": f"cinematic mysterious 8k shot of {topic}"},
        {"speech": f"इसकी सबसे अनोखी बात यह है कि इसका असर हमारी सोच से भी कहीं ज़्यादा गहरा होता है।", "visual_prompt": f"detailed close-up dynamic angle of {topic}, photorealistic"},
        {"speech": f"यही वजह है कि आज {topic} पूरी दुनिया में सबसे अलग और चर्चा का विषय बना हुआ है।", "visual_prompt": f"epic cinematic wide view of {topic}, dramatic lighting"}
    ]

def render_with_creatomate(scenes):
    elements = []
    current_time = 0.0
    scene_dur = 4.0

    for sc in scenes:
        prompt_enc = requests.utils.quote(sc["visual_prompt"] + ", vertical 9:16 portrait orientation, cinematic, photorealistic, 8k resolution")
        img_url = f"https://image.pollinations.ai/prompt/{prompt_enc}?width=1080&height=1920&nologo=true&model=turbo"

        # बैकग्राउंड इमेज + ज़ूम इफ़ेक्ट
        elements.append({
            "type": "image",
            "url": img_url,
            "time": current_time,
            "duration": scene_dur,
            "fit": "cover",
            "animations": [
                {
                    "time": "start",
                    "duration": scene_dur,
                    "easing": "linear",
                    "type": "scale",
                    "scale_start": "100%",
                    "scale_end": "115%"
                }
            ]
        })

        # टेक्स्ट टू स्पीच
        elements.append({
            "type": "audio",
            "source": "text-to-speech",
            "voice": "hi-IN-MadhurNeural",
            "text": sc["speech"],
            "time": current_time
        })

        # बोल्ड पीले सबटाइटल्स
        elements.append({
            "type": "text",
            "text": sc["speech"],
            "time": current_time,
            "duration": scene_dur,
            "y": "74%",
            "width": "86%",
            "font_family": "Noto Sans Devanagari",
            "font_size": "54 px",
            "font_weight": "bold",
            "fill_color": "#FFE600",
            "stroke_color": "#000000",
            "stroke_width": "8 px",
            "x_alignment": "50%",
            "y_alignment": "50%"
        })

        current_time += scene_dur

    headers = {
        "Authorization": f"Bearer {CREATOMATE_API_KEY}",
        "Content-Type": "application/json"
    }

    # मान्य Creatomate JSON स्कीमा
    render_payload = {
        "source": {
            "output_format": "mp4",
            "frame_rate": 60,
            "width": 1080,
            "height": 1920,
            "elements": elements
        }
    }

    res = requests.post("https://api.creatomate.com/v1/renders", headers=headers, json=render_payload, timeout=20)
    if res.status_code not in (200, 202):
        raise Exception(f"Creatomate Error: {res.text}")

    render_data = res.json()[0]
    render_id = render_data["id"]

    for _ in range(35):
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

    wait_msg = await update.message.reply_text(f"🚀 '{topic}' पर 60 FPS ओरिजिनल रील तैयार हो रही है...")
    try:
        scenes = generate_script_dynamic(topic)
        script_text = "\n\n".join([s["speech"] for s in scenes])
        await update.message.reply_text(f"📝 *ओरिजिनल स्क्रिप्ट:*\n\n{script_text}", parse_mode="Markdown")

        video_url = render_with_creatomate(scenes)
        await update.message.reply_video(video=video_url, caption=f"🔥 60 FPS HD: {topic}")

    except Exception as e:
        await update.message.reply_text(f"⚠️ एरर: {str(e)}")
    finally:
        gc.collect()
        try:
            await wait_msg.delete()
        except Exception:
            pass

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("👑 Hermes AI Studio लाइव है!\n\nनई रील बनाने के लिए भेजें:\n`/reel <विषय>`")

if __name__ == "__main__":
    threading.Thread(target=run_http_server, daemon=True).start()
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("reel", generate_reel))
    app.run_polling()
