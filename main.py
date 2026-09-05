import os
import io
import json
import random
import threading
import requests
from http.server import HTTPServer, BaseHTTPRequestHandler
from PIL import Image, ImageDraw, ImageFont
import numpy as np
import google.generativeai as genai
import edge_tts
from moviepy import VideoFileClip, AudioFileClip, ImageClip, concatenate_videoclips, CompositeVideoClip
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes

class SimpleHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Hermes Pro Video Engine Active")

def run_http_server():
    port = int(os.environ.get("PORT", 10000))
    server = HTTPServer(("0.0.0.0", port), SimpleHandler)
    server.serve_forever()

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
PEXELS_API_KEY = os.getenv("PEXELS_API_KEY", "")

genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel("models/gemini-3.6-flash")

def create_subtitle_image(text, width=1080, height=1920):
    img = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    try:
        font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 46)
    except Exception:
        font = ImageFont.load_default()

    words = text.split()
    lines, current_line = [], []
    for w in words:
        current_line.append(w)
        if len(" ".join(current_line)) > 24:
            lines.append(" ".join(current_line[:-1]))
            current_line = [w]
    if current_line:
        lines.append(" ".join(current_line))

    y_pos = int(height * 0.72)
    for line in lines:
        bbox = draw.textbbox((0, 0), line, font=font)
        text_w = bbox[2] - bbox[0]
        text_h = bbox[3] - bbox[1]
        x_pos = (width - text_w) // 2

        pad = 12
        draw.rectangle(
            [x_pos - pad, y_pos - pad, x_pos + text_w + pad, y_pos + text_h + pad],
            fill=(0, 0, 0, 190)
        )
        draw.text((x_pos, y_pos), line, fill=(255, 230, 0, 255), font=font)
        y_pos += text_h + 20

    return np.array(img)

def fetch_pexels_clip(query, target_duration=4):
    if not PEXELS_API_KEY:
        return None
    headers = {"Authorization": PEXELS_API_KEY}
    url = f"https://api.pexels.com/videos/search?query={query}&orientation=portrait&per_page=4"
    try:
        r = requests.get(url, headers=headers, timeout=10).json()
        videos = r.get("videos", [])
        if not videos:
            url_alt = "https://api.pexels.com/videos/search?query=cinematic+technology&orientation=portrait&per_page=4"
            videos = requests.get(url_alt, headers=headers, timeout=10).json().get("videos", [])
        if videos:
            vid = random.choice(videos)
            files = [f for f in vid.get("video_files", []) if f.get("height", 0) > f.get("width", 0)]
            link = files[0]["link"] if files else vid["video_files"][0]["link"]
            file_name = f"clip_{random.randint(100, 999)}.mp4"
            with requests.get(link, stream=True, timeout=15) as res:
                with open(file_name, "wb") as f:
                    for chunk in res.iter_content(chunk_size=1024 * 512):
                        f.write(chunk)
            return file_name
    except Exception:
        pass
    return None

async def build_viral_reel(topic):
    prompt = f"""
    विषय: '{topic}'
    यूट्यूब शॉर्ट्स और रील्स के लिए 3 सीन्स का स्ट्रक्चर JSON फॉर्मेट में दो।
    प्रत्येक सीन 5 से 7 सेकंड का होना चाहिए।
    आउटपुट केवल यह वैध JSON दें, कोई अतिरिक्त टेक्स्ट न लिखें:
    {{
      "full_script": "पूरी 20-25 सेकंड की हिंदी बोलने वाली स्क्रिप्ट",
      "scenes": [
        {{"text": "पहला हिंदी हुक वाक्य", "search_term": "visual search query in english"}},
        {{"text": "दूसरा मुख्य पॉइंट वाक्य", "search_term": "visual search query in english"}},
        {{"text": "तीसरा निष्कर्ष वाक्य", "search_term": "visual search query in english"}}
      ]
    }}
    """
    res = model.generate_content(prompt)
    raw_text = res.text.replace("```json", "").replace("```", "").strip()
    data = json.loads(raw_text)

    full_script = data["full_script"]
    scenes = data["scenes"]

    audio_path = "full_voice.mp3"
    comm = edge_tts.Communicate(full_script, voice="hi-IN-MadhurNeural")
    await comm.save(audio_path)
    audio_clip = AudioFileClip(audio_path)
    total_duration = audio_clip.duration
    scene_duration = total_duration / len(scenes)

    downloaded_clips = []
    video_segments = []

    for item in scenes:
        clip_file = fetch_pexels_clip(item["search_term"], scene_duration)
        if clip_file and os.path.exists(clip_file):
            downloaded_clips.append(clip_file)
            vc = VideoFileClip(clip_file)
            if hasattr(vc, "subclipped"):
                vc = vc.subclipped(0, min(vc.duration, scene_duration))
            else:
                vc = vc.subclip(0, min(vc.duration, scene_duration))
            
            sub_arr = create_subtitle_image(item["text"])
            txt_clip = ImageClip(sub_arr).with_duration(vc.duration) if hasattr(ImageClip, "with_duration") else ImageClip(sub_arr).set_duration(vc.duration)
            combined_segment = CompositeVideoClip([vc, txt_clip])
            video_segments.append(combined_segment)

    final_video = "viral_reel_out.mp4"
    if video_segments:
        final_track = concatenate_videoclips(video_segments, method="compose")
        final_with_audio = final_track.with_audio(audio_clip) if hasattr(final_track, "with_audio") else final_track.set_audio(audio_clip)
        final_with_audio.write_videofile(
            final_video,
            codec="libx264",
            audio_codec="aac",
            fps=24,
            preset="ultrafast",
            logger=None
        )
        final_track.close()
        final_with_audio.close()

    audio_clip.close()
    for seg in video_segments:
        seg.close()
    for d in downloaded_clips:
        if os.path.exists(d):
            os.remove(d)

    return full_script, audio_path, final_video

async def generate_reel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    topic = " ".join(context.args)
    if not topic:
        await update.message.reply_text("विषय लिखें। उदाहरण: `/reel ब्लैक होल का सच`")
        return

    wait_msg = await update.message.reply_text("⚡ प्रो-क्वालिटी मल्टी-क्लिप और सबटाइटल्स रेंडर हो रहे हैं...")
    try:
        script, audio, video = await build_viral_reel(topic)
        await update.message.reply_text(f"📝 *स्क्रिप्ट:*\n\n{script}", parse_mode="Markdown")

        if video and os.path.exists(video):
            with open(video, "rb") as vf:
                await update.message.reply_video(video=vf, caption=f"🚀 वायरल रील: {topic}")
            os.remove(video)
        else:
            with open(audio, "rb") as af:
                await update.message.reply_voice(voice=af, caption="🎙️ वॉइसओवर")

        if os.path.exists(audio):
            os.remove(audio)
    except Exception as e:
        await update.message.reply_text(f"⚠️ एरर: {str(e)}")
    finally:
        await wait_msg.delete()

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("👑 Hermes Pro AI Studio लाइव है!\n\nरील बनाने के लिए भेजें:\n`/reel <कोई भी विषय>`")

if __name__ == "__main__":
    threading.Thread(target=run_http_server, daemon=True).start()
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("reel", generate_reel))
    app.run_polling()
