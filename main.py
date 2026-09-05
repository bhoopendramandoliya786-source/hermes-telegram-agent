import os
import gc
import re
import json
import random
import threading
import subprocess
import requests
from http.server import HTTPServer, BaseHTTPRequestHandler
from PIL import Image, ImageDraw, ImageFont
import google.generativeai as genai
import edge_tts
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
    return re.sub(r'\s+', ' ', text).strip()

def download_pexels_clip(query, out_filename):
    if not PEXELS_API_KEY:
        return False
    clean_q = requests.utils.quote(query)
    url = f"https://api.pexels.com/videos/search?query={clean_q}&orientation=portrait&per_page=5"
    headers = {"Authorization": PEXELS_API_KEY}
    try:
        res = requests.get(url, headers=headers, timeout=10).json()
        videos = res.get("videos", [])
        if not videos:
            alt_url = "https://api.pexels.com/videos/search?query=cinematic+galaxy&orientation=portrait&per_page=5"
            videos = requests.get(alt_url, headers=headers, timeout=10).json().get("videos", [])
        if videos:
            vid = random.choice(videos)
            files = [f for f in vid.get("video_files", []) if f.get("height", 0) > f.get("width", 0)]
            target = files[0]["link"] if files else vid["video_files"][0]["link"]
            with requests.get(target, stream=True, timeout=15) as r:
                with open(out_filename, "wb") as f:
                    for chunk in r.iter_content(chunk_size=1024*256):
                        f.write(chunk)
            return True
    except Exception as e:
        print(f"Pexels error: {e}")
    return False

def make_subtitle_png(text, png_filename):
    ensure_hindi_font()
    img = Image.new("RGBA", (540, 960), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    try:
        font = ImageFont.truetype(FONT_PATH, 28)
    except Exception:
        font = ImageFont.load_default()

    words = clean_for_speech(text).split()
    lines, cur = [], []
    for w in words:
        cur.append(w)
        if len(" ".join(cur)) > 18:
            lines.append(" ".join(cur[:-1]))
            cur = [w]
    if cur:
        lines.append(" ".join(cur))

    y = int(960 * 0.70)
    for line in lines:
        bbox = draw.textbbox((0, 0), line, font=font)
        tw = bbox[2] - bbox[0]
        th = bbox[3] - bbox[1]
        x = (540 - tw) // 2
        pad = 8
        draw.rectangle([x - pad, y - pad, x + tw + pad, y + th + pad], fill=(0, 0, 0, 210))
        draw.text((x, y), line, fill=(255, 230, 0, 255), font=font)
        y += th + 12
    img.save(png_filename)

async def build_viral_reel(topic):
    prompt = f"""
    Topic: '{topic}'
    YouTube Shorts aur Reels ke liye 3 scenes ka structure JSON me do.
    Output ONLY valid JSON:
    {{
      "full_script": "20 second ki Hindi voiceover script",
      "scenes": [
        {{"text": "Scene 1 Subtitle", "search": "space galaxy cinematic"}},
        {{"text": "Scene 2 Subtitle", "search": "black hole cosmic"}},
        {{"text": "Scene 3 Subtitle", "search": "stars nebula cinematic"}}
      ]
    }}
    """
    res = model.generate_content(prompt)
    raw = res.text.replace("```json", "").replace("```", "").strip()
    match = re.search(r'\{.*\}', raw, re.DOTALL)
    data = json.loads(match.group(0)) if match else json.loads(raw)

    full_script = data.get("full_script", f"{topic} के बारे में रोचक तथ्य।")
    scenes = data.get("scenes", [])

    audio_file = "voice.mp3"
    comm = edge_tts.Communicate(clean_for_speech(full_script), voice="hi-IN-MadhurNeural")
    await comm.save(audio_file)

    # Get audio duration using ffprobe (Zero RAM usage)
    probe_cmd = f"ffprobe -v error -show_entries format=duration -of default=noprint_wrappers=1:nokey=1 {audio_file}"
    try:
        dur_out = subprocess.check_output(probe_cmd, shell=True).decode().strip()
        total_dur = max(6.0, float(dur_out))
    except Exception:
        total_dur = 20.0

    scene_dur = round(total_dur / max(1, len(scenes)), 2)
    rendered_segments = []
    temp_files = [audio_file]

    for idx, sc in enumerate(scenes):
        raw_clip = f"raw_{idx}.mp4"
        sub_png = f"sub_{idx}.png"
        seg_out = f"seg_{idx}.mp4"
        temp_files.extend([raw_clip, sub_png, seg_out])

        ok = download_pexels_clip(sc.get("search", topic), raw_clip)
        if not ok or not os.path.exists(raw_clip):
            download_pexels_clip("cinematic space", raw_clip)

        make_subtitle_png(sc.get("text", ""), sub_png)

        # Ultra-lightweight FFmpeg overlay (max 50 MB RAM)
        ff_cmd = (
            f"ffmpeg -y -t {scene_dur} -i {raw_clip} -i {sub_png} "
            f"-filter_complex \"[0:v]scale=540:960:force_original_aspect_ratio=increase,crop=540:960[v0];"
            f"[v0][1:v]overlay=0:0[vout]\" -map \"[vout]\" -r 24 -c:v libx264 -preset ultrafast "
            f"-threads 1 -an {seg_out}"
        )
        subprocess.run(ff_cmd, shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if os.path.exists(seg_out):
            rendered_segments.append(seg_out)

    # Concatenate clips and merge audio via FFmpeg
    concat_list = "concat_list.txt"
    temp_files.append(concat_list)
    with open(concat_list, "w") as f:
        for seg in rendered_segments:
            f.write(f"file '{os.path.abspath(seg)}'\n")

    final_video = "viral_reel.mp4"
    temp_files.append(final_video)

    merge_cmd = (
        f"ffmpeg -y -f concat -safe 0 -i {concat_list} -i {audio_file} "
        f"-c:v copy -c:a aac -shortest {final_video}"
    )
    subprocess.run(merge_cmd, shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    gc.collect()

    return full_script, audio_file, final_video, temp_files

async def generate_reel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    topic = clean_for_speech(" ".join(context.args))
    if not topic:
        await update.message.reply_text("कृपया विषय लिखें। उदाहरण: `/reel अंतरिक्ष के रहस्य`")
        return

    wait_msg = await update.message.reply_text("⚡ FFmpeg इंजन से बिना मेमोरी लोड के रील रेंडर हो रही है...")
    temp_files = []
    try:
        script, audio, video, temp_files = await build_viral_reel(topic)
        await update.message.reply_text(f"📝 *स्क्रिप्ट:*\n\n{script}", parse_mode="Markdown")

        if os.path.exists(video) and os.path.getsize(video) > 5000:
            with open(video, "rb") as vf:
                await update.message.reply_video(video=vf, caption=f"🔥 रील तैयार: {topic}")
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
    await update.message.reply_text("👑 Hermes Pro AI Studio सक्रिय है!\n\nरील बनाने के लिए लिखें:\n`/reel <विषय>`")

if __name__ == "__main__":
    ensure_hindi_font()
    threading.Thread(target=run_http_server, daemon=True).start()
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("reel", generate_reel))
    app.run_polling()
