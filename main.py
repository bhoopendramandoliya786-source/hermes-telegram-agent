import os
import gc
import re
import json
import time
import threading
import requests
from http.server import HTTPServer, BaseHTTPRequestHandler
import edge_tts
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

class SimpleHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Hermes Creatomate Cloud Engine Running")

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
    if not GEMINI_API_KEY:
        raise Exception("GEMINI_API_KEY Render Environment में सेट नहीं है!")

    headers = {"Content-Type": "application/json"}
    prompt = f"""
Write an extremely engaging 3-scene Hindi YouTube Shorts / Reel script about the topic: '{topic}'.
MANDATORY RULES:
- Provide REAL, SPECIFIC, UNIQUE facts about '{topic}'.
- Strictly DO NOT use generic filler sentences like 'क्या आप जानते हैं', 'इसके पीछे का सच', or 'वैज्ञानिकों ने हाल ही में खुलासा किया'.
- Scene 1: Direct curiosity hook about '{topic}'.
- Scene 2: The most shocking fact or mechanism about '{topic}'.
- Scene 3: Practical impact or conclusion.
- Visual prompts MUST directly describe '{topic}' in detailed cinematic English.

Return ONLY valid JSON matching this schema:
{{
  "scenes": [
    {{"speech": "पहला सीन वाक्य हिंदी में", "visual_prompt": "cinematic hyperrealistic 8k shot of {topic}, dramatic lighting"}},
    {{"speech": "दूसरा सीन वाक्य हिंदी में", "visual_prompt": "cinematic macro close-up shot showing detail of {topic}, 8k"}},
    {{"speech": "तीसरा सीन वाक्य हिंदी में", "visual_prompt": "epic cinematic wide angle view of {topic}, masterpiece"}}
  ]
}}
"""
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": 0.7,
            "response_mime_type": "application/json"
        }
    }

    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-3.6-flash:generateContent?key={GEMINI_API_KEY}"
    res = requests.post(url, headers=headers, json=payload, timeout=45)
    if res.status_code != 200:
        raise Exception(f"Gemini API Error: {res.text[:150]}")

    data = res.json()
    out_text = data['candidates'][0]['content']['parts'][0]['text']
    parsed = json.loads(re.search(r'\{.*\}', out_text, re.DOTALL).group(0))
    return parsed["scenes"]

def upload_to_creatomate(file_path):
    headers = {"Authorization": f"Bearer {CREATOMATE_API_KEY}"}
    with open(file_path, "rb") as f:
        r = requests.post("https://api.creatomate.com/v1/uploads", headers=headers, data=f, timeout=30)
    if r.status_code not in (200, 201):
        raise Exception(f"Upload failed: {r.text}")
    return r.json()["url"]

async def render_cloud_reel(scenes, topic):
    if not CREATOMATE_API_KEY:
        raise Exception("CREATOMATE_API_KEY Render Environment में मौजूद नहीं है!")

    elements = []
    current_time = 0.0
    temp_files = []

    for idx, sc in enumerate(scenes):
        speech_text = clean_text(sc["speech"])
        aud_file = f"cloud_aud_{idx}.mp3"
        img_file = f"cloud_img_{idx}.jpg"
        temp_files.extend([aud_file, img_file])

        # 1. Edge-TTS ऑडियो जनरेट
        comm = edge_tts.Communicate(speech_text, voice="hi-IN-MadhurNeural", rate="+15%")
        await comm.save(aud_file)

        # 2. इमेज डाउनलोड
        clean_p = requests.utils.quote(f"{sc['visual_prompt']}, vertical 9:16, cinematic, photorealistic, 8k")
        img_url_pol = f"https://image.pollinations.ai/prompt/{clean_p}?width=1080&height=1920&nologo=true&model=turbo"
        try:
            r = requests.get(img_url_pol, timeout=20)
            with open(img_file, "wb") as f:
                f.write(r.content)
        except Exception:
            # बैकअप इमेज
            r = requests.get("https://images.unsplash.com/photo-1518837695005-2083093ee35b?auto=format&fit=crop&w=1080&h=1920&q=80", timeout=10)
            with open(img_file, "wb") as f:
                f.write(r.content)

        # Creatomate CDN पर सुरक्षित अपलोड
        cloud_aud_url = upload_to_creatomate(aud_file)
        cloud_img_url = upload_to_creatomate(img_file)

        # सीन की अवधि (5.0 सेकंड प्रति सीन)
        scene_dur = 5.0

        # बैकग्राउंड इमेज + स्मूथ ज़ूम इन
        elements.append({
            "type": "image",
            "url": cloud_img_url,
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

        # वॉयसओवर ऑडियो
        elements.append({
            "type": "audio",
            "url": cloud_aud_url,
            "time": current_time
        })

        # बोल्ड सबटाइटल
        elements.append({
            "type": "text",
            "text": speech_text,
            "time": current_time,
            "duration": scene_dur,
            "y": "65%",
            "width": "85%",
            "font_family": "Noto Sans Devanagari",
            "font_size": "52 px",
            "font_weight": "bold",
            "fill_color": "#FFE600",
            "stroke_color": "#000000",
            "stroke_width": "8 px",
            "background_color": "rgba(0,0,0,0.7)",
            "background_border_radius": "12 px",
            "x_alignment": "50%",
            "y_alignment": "50%"
        })

        current_time += scene_dur

    # बैकग्राउंड म्यूज़िक
    elements.append({
        "type": "audio",
        "url": "https://cdn.pixabay.com/download/audio/2022/05/27/audio_1808fbf07a.mp3?filename=ambient-cinematic-112282.mp3",
        "time": 0.0,
        "duration": current_time,
        "volume": 0.12
    })

    # Creatomate API रेंडर रिक्वेस्ट
    headers = {
        "Authorization": f"Bearer {CREATOMATE_API_KEY}",
        "Content-Type": "application/json"
    }

    render_payload = {
        "source": {
            "output_format": "mp4",
            "frame_rate": 60,
            "width": 1080,
            "height": 1920,
            "elements": elements
        }
    }

    res = requests.post("https://api.creatomate.com/v1/renders", headers=headers, json=render_payload, timeout=30)
    if res.status_code not in (200, 202):
        raise Exception(f"Creatomate Error: {res.text}")

    render_id = res.json()[0]["id"]

    # स्टेटस चेक
    final_video_url = None
    for _ in range(45):
        time.sleep(2)
        check = requests.get(f"https://api.creatomate.com/v1/renders/{render_id}", headers=headers, timeout=15)
        info = check.json()
        if info.get("status") == "succeeded":
            final_video_url = info.get("url")
            break
        elif info.get("status") == "failed":
            raise Exception("Creatomate render failed.")

    # लोकल फाइल्स डिलीट
    for f in temp_files:
        if os.path.exists(f):
            try:
                os.remove(f)
            except Exception:
                pass

    if not final_video_url:
        raise Exception("क्लाउड रेंडरिंग टाइमआउट हो गई।")

    return final_video_url

async def generate_reel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    topic = clean_text(" ".join(context.args))
    if not topic:
        await update.message.reply_text("कृपया विषय लिखें। उदाहरण: `/reel वायुमंडल का रहस्य`")
        return

    wait_msg = await update.message.reply_text(f"🚀 '{topic}' पर 60 FPS क्लाउड रेंडरिंग शुरू हो रही है...")
    try:
        scenes = generate_script_dynamic(topic)
        script_text = "\n\n".join([f"🎬 *सीन {i+1}:* {s['speech']}" for i, s in enumerate(scenes)])
        await update.message.reply_text(f"📝 *स्क्रिप्ट:*\n\n{script_text}", parse_mode="Markdown")

        video_url = await render_cloud_reel(scenes, topic)
        await update.message.reply_video(video=video_url, caption=f"🔥 60 FPS HD रील: {topic}")

    except Exception as e:
        await update.message.reply_text(f"❌ *एरर:*\n`{str(e)}`", parse_mode="Markdown")
    finally:
        gc.collect()
        try:
            await wait_msg.delete()
        except Exception:
            pass

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("👑 Hermes Creatomate 60FPS Cloud Studio सक्रिय है!\n\nरील बनाने के लिए भेजें:\n`/reel <विषय>`")

if __name__ == "__main__":
    threading.Thread(target=run_http_server, daemon=True).start()
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("reel", generate_reel))
    app.run_polling()
