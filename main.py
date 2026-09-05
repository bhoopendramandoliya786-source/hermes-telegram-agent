import os
import gc
import re
import json
import random
import threading
import requests
from http.server import HTTPServer, BaseHTTPRequestHandler
from PIL import Image, ImageDraw, ImageFont
import google.generativeai as genai
import edge_tts
from moviepy import VideoFileClip, AudioFileClip, ImageClip, CompositeVideoClip, concatenate_videoclips
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

class SimpleHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Hermes Video Engine Active")

def run_http_server():
    port = int(os.environ.get("PORT", 10000))
    server = HTTPServer(("0.0.0.0", port), SimpleHandler)
    server.serve_forever()

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
PEXELS_API_KEY = os.getenv("PEXELS_API_KEY", "")

genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel("models/gemini-3.6-flash")

FONT_PATH = "hindi_font.ttf"
def ensure_hindi_font():
    if not os.path.exists(FONT_PATH):
        font_url = "https://raw.githubusercontent.com/googlefonts/noto-fonts/main/hinted/ttf/NotoSansDevanagari/NotoSansDevanagari-Bold.ttf"
        try:
            r = requests.get(font_url, timeout=15)
            if r.status_code == 200:
                with open(FONT_PATH, "wb") as f:
                    f.write(r.content)
        except Exception:
            pass

def clean_for_speech(text):
    text = re.sub(r'[*_~`#\[\]\(\)\<\>\"\'\\]', ' ', text)
    text = re.sub(r'\s+', ' ', text).strip()
    return text

def download_pexels_clip(query, duration=5):
    if not PEXELS_API_KEY:
        return None
    headers = {"Authorization": PEXELS_API_KEY}
    clean_q = requests.utils.quote(query)
    url = f"https://api.pexels.com/videos/search?query={clean_q}&orientation=portrait&per_page=5"
    try:
        res = requests.get(url, headers=headers, timeout=12).json()
        videos = res.get("videos", [])
        if not videos:
            alt_url = "https://api.pexels.com/videos/search?query=cinematic+space&orientation=portrait&per_page=5"
            videos = requests.get(alt_url, headers=headers, timeout=12).json().get("videos", [])
        
        if videos:
            vid = random.choice(videos)
            files = [f for f in vid.get("video_files", []) if f.get("height", 0) > f.get("width", 0)]
            target = files[0] if files else vid["video_files"][0]
            
            clip_name = f"clip_{random.randint(100, 999)}.mp4"
            with requests.get(target["link"], stream=True, timeout=15) as r:
                with open(clip_name, "wb") as f:
                    for chunk in r.iter_content(chunk_size=1024*512):
                        f.write(chunk)
            return clip_name
    except Exception as e:
        print(f"Pexels error: {e}")
    return None

def create_subtitle_clip(text, duration, width=540, height=960):
    ensure_hindi_font()
    img = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    try:
        font = ImageFont.truetype(FONT_PATH, 30)
    except Exception:
        font = ImageFont.load_default()

    words = clean_for_speech(text).split()
    lines, current = [], []
    for w in words:
        current.append(w)
        if len(" ".join(current)) > 16:
            lines.append(" ".join(current[:-1]))
            current = [w]
    if current:
        lines.append(" ".join(current))

    y = int(height * 0.70)
    for line in lines:
        bbox = draw.textbbox((0, 0), line, font=font)
        tw = bbox[2] - bbox[0]
        th = bbox[3] - bbox[1]
        x = (width - tw) // 2

        pad = 8
        draw.rectangle([x - pad, y - pad, x + tw + pad, y + th + pad], fill=(0, 0, 0, 210))
        draw.text((x, y), line, fill=(255, 230, 0, 255), font=font)
        y += th + 12

    img_path = f"sub_{random.randint(100, 999)}.png"
    img.save(img_path)
    try:
        sub_clip = ImageClip(img_path, duration=duration)
    except Exception:
        sub_clip = ImageClip(img_path)
        sub_clip.duration = duration
    return sub_clip, img_path

async def build_viral_reel(topic):
    prompt = f"""
    Topic: '{topic}'
    YouTube Shorts aur Reels ke liye 3 scenes ka structure JSON me do.
    Pexels search term English me exact visual ke liye do.
    Output ONLY valid JSON:
    {{
      "full_script": "20-25 second ki hindi voiceover script",
      "scenes": [
        {{"text": "Scene 1 Hindi Subtitle", "search": "accurate english query (e.g. space galaxy cinematic)"}},
        {{"text": "Scene 2 Hindi Subtitle", "search": "accurate english query (e.g. black hole universe)"}},
        {{"text": "Scene 3 Hindi Subtitle", "search": "accurate english query (e.g. stars cosmic explosion)"}}
      ]
    }}
    """
    res = model.generate_content(prompt)
    raw = res.text.replace("```json", "").replace("```", "").strip()
    match = re.search(r'\{.*\}', raw, re.DOTALL)
    data = json.loads(match.group(0)) if match else json.loads(raw)

    full_script = data.get("full_script", f"{topic} के बारे में जानिए।")
    scenes = data.get("scenes", [])

    audio_path = "voiceover.mp3"
    comm = edge_tts.Communicate(clean_for_speech(full_script), voice="hi-IN-MadhurNeural")
    await comm.save(audio_path)

    audio_clip = AudioFileClip(audio_path)
    total_dur = max(6.0, audio_clip.duration)
    scene_dur = total_dur / len(scenes)

    video_segments = []
    temp_files = [audio_path]

    for sc in scenes:
        clip_file = download_pexels_clip(sc.get("search", topic), scene_dur)
        if not clip_file or not os.path.exists(clip_file):
            clip_file = download_pexels_clip("universe", scene_dur)

        if clip_file and os.path.exists(clip_file):
            temp_files.append(clip_file)
            vc = VideoFileClip(clip_file)
            
            # Subclip safe call
            clip_dur = min(vc.duration, scene_dur)
            vc = vc.subclipped(0, clip_dur) if hasattr(vc, "subclipped") else vc.subclip(0, clip_dur)
            vc = vc.resized(newsize=(540, 960)) if hasattr(vc, "resized") else vc.resize((540, 960))

            sub_clip, sub_img = create_subtitle_clip(sc.get("text", ""), vc.duration)
            temp_files.append(sub_img)

            combined = CompositeVideoClip([vc, sub_clip])
            video_segments.append(combined)

    final_out = "viral_reel_out.mp4"
    temp_files.append(final_out)

    final_track = concatenate_videoclips(video_segments, method="compose")
    final_with_audio = final_track.with_audio(audio_clip) if hasattr(final_track, "with_audio") else final_track.set_audio(audio_clip)

    final_with_audio.write_videofile(
        final_out,
        fps=20,
        codec="libx264",
        audio_codec="aac",
        preset="ultrafast",
        threads=1,
        logger=None
    )

    audio_clip.close()
    final_track.close()
    final_with_audio.close()
    for seg in video_segments:
        seg.close()

    gc.collect()
    return full_script, audio_path, final_out, temp_files

async def generate_reel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    topic = " ".join(context.args)
    if not topic:
        await update.message.reply_text("कृपया विषय लिखें। उदाहरण: `/reel अंतरिक्ष के रहस्य`")
        return

    wait_msg = await update.message.reply_text("⚡ HD विजुअल्स और हिंदी सबटाइटल्स सिंक हो रहे हैं...")
    temp_files = []
    try:
        script, audio, video, temp_files = await build_viral_reel(topic)
        await update.message.reply_text(f"📝 *स्क्रिप्ट:*\n\n{script}", parse_mode="Markdown")

        if os.path.exists(video):
            with open(video, "rb") as vf:
                await update.message.reply_video(video=vf, caption=f"🔥 रील: {topic}")
        else:
            with open(audio, "rb") as af:
                await update.message.reply_voice(voice=af, caption="🎙️ वॉइसओवर")

    except Exception as e:
        await update.message.reply_text(f"⚠️ एरर: {str(e)}")
    finally:
        for f in temp_files:
            if os.path.exists(f):
                try:
                    os.remove(f)
                except Exception:
                    pass
        gc.collect()
        await wait_msg.delete()

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("👑 Hermes Video Engine सक्रिय है!\n\nरील बनाने के लिए लिखें:\n`/reel <विषय>`")

if __name__ == "__main__":
    ensure_hindi_font()
    threading.Thread(target=run_http_server, daemon=True).start()
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("reel", generate_reel))
    app.run_polling()
