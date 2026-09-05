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
        self.wfile.write(b"Hermes HD Video Engine Running")

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
BGM_PATH = "bgm.mp3"

def ensure_assets():
    if not os.path.exists(FONT_PATH):
        font_url = "https://raw.githubusercontent.com/googlefonts/noto-fonts/main/hinted/ttf/NotoSansDevanagari/NotoSansDevanagari-Bold.ttf"
        try:
            r = requests.get(font_url, timeout=15)
            if r.status_code == 200:
                with open(FONT_PATH, "wb") as f:
                    f.write(r.content)
        except Exception:
            pass

    if not os.path.exists(BGM_PATH):
        bgm_url = "https://cdn.pixabay.com/download/audio/2022/05/27/audio_1808fbf07a.mp3?filename=ambient-cinematic-112282.mp3"
        try:
            r = requests.get(bgm_url, timeout=20)
            if r.status_code == 200:
                with open(BGM_PATH, "wb") as f:
                    f.write(r.content)
        except Exception:
            pass

def clean_for_speech(text):
    text = re.sub(r'[*_~`#\[\]\(\)\<\>\"\'\\]', ' ', text)
    return re.sub(r'\s+', ' ', text).strip()

def get_file_duration(file_path):
    cmd = f"ffprobe -v error -show_entries format=duration -of default=noprint_wrappers=1:nokey=1 \"{file_path}\""
    try:
        out = subprocess.check_output(cmd, shell=True).decode().strip()
        return max(2.5, float(out))
    except Exception:
        return 5.0

def download_pexels_clip(query, out_filename):
    if not PEXELS_API_KEY:
        return False
    clean_q = requests.utils.quote(query)
    url = f"https://api.pexels.com/videos/search?query={clean_q}&orientation=portrait&per_page=6"
    headers = {"Authorization": PEXELS_API_KEY}
    try:
        res = requests.get(url, headers=headers, timeout=12).json()
        videos = res.get("videos", [])
        if not videos:
            alt_url = "https://api.pexels.com/videos/search?query=cinematic+luxury+nature&orientation=portrait&per_page=6"
            videos = requests.get(alt_url, headers=headers, timeout=12).json().get("videos", [])
        if videos:
            vid = random.choice(videos)
            files = [f for f in vid.get("video_files", []) if f.get("height", 0) > f.get("width", 0)]
            target = files[0]["link"] if files else vid["video_files"][0]["link"]
            with requests.get(target, stream=True, timeout=20) as r:
                with open(out_filename, "wb") as f:
                    for chunk in r.iter_content(chunk_size=1024*512):
                        f.write(chunk)
            return True
    except Exception as e:
        print(f"Pexels error: {e}")
    return False

def make_subtitle_png(text, png_filename, width=1080, height=1920):
    ensure_assets()
    img = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    try:
        font = ImageFont.truetype(FONT_PATH, 56)
    except Exception:
        font = ImageFont.load_default()

    words = clean_for_speech(text).split()
    lines, cur = [], []
    for w in words:
        cur.append(w)
        if len(" ".join(cur)) > 16:
            lines.append(" ".join(cur[:-1]))
            cur = [w]
    if cur:
        lines.append(" ".join(cur))

    y = int(height * 0.70)
    for line in lines:
        bbox = draw.textbbox((0, 0), line, font=font)
        tw = bbox[2] - bbox[0]
        th = bbox[3] - bbox[1]
        x = (width - tw) // 2
        pad = 16
        draw.rectangle([x - pad, y - pad, x + tw + pad, y + th + pad], fill=(0, 0, 0, 210))
        draw.text((x, y), line, fill=(255, 230, 0, 255), font=font)
        y += th + 24
    img.save(png_filename)

async def build_viral_reel(topic):
    prompt = f"""
    Topic: '{topic}'
    YouTube Shorts/Reels ke liye exactly 3 scenes ka structure JSON me do.
    Har scene ka Hindi speech sentence aur uska accurate visual search query do.
    Output ONLY valid JSON:
    {{
      "scenes": [
        {{"speech": "पहला आकर्षक हुक वाक्य", "search": "accurate english query (e.g. intense gym workout dumbbell)"}},
        {{"text_overlay": "पहला बोल्ड सबटाइटल", "speech": "दूसरा मुख्य पॉइंट वाक्य", "search": "accurate english query (e.g. running athlete cinematic)"}},
        {{"text_overlay": "दूसरा बोल्ड सबटाइटल", "speech": "तीसरा निष्कर्ष वाक्य", "search": "accurate english query (e.g. champion victory fitness)"}}
      ]
    }}
    """
    res = model.generate_content(prompt)
    raw = res.text.replace("```json", "").replace("```", "").strip()
    match = re.search(r'\{.*\}', raw, re.DOTALL)
    data = json.loads(match.group(0)) if match else json.loads(raw)

    scenes = data.get("scenes", [])
    if len(scenes) < 2:
        scenes = [
            {"speech": f"क्या आप जानते हैं {topic} के बारे में?", "search": "cinematic dramatic"},
            {"speech": "यह जानकारी आपकी सोच बदल कर रख देगी।", "search": "universe stars space"},
            {"speech": "ऐसी ही काम की बातों के लिए अभी सब्सक्राइब करें।", "search": "sunset motivation cinematic"}
        ]

    rendered_segments = []
    temp_files = []
    full_script_lines = []

    for idx, sc in enumerate(scenes):
        speech_text = clean_for_speech(sc.get("speech", ""))
        sub_text = clean_for_speech(sc.get("text_overlay", speech_text))
        full_script_lines.append(speech_text)

        scene_audio = f"audio_{idx}.mp3"
        raw_clip = f"raw_{idx}.mp4"
        sub_png = f"sub_{idx}.png"
        seg_out = f"seg_{idx}.mp4"
        temp_files.extend([scene_audio, raw_clip, sub_png, seg_out])

        comm = edge_tts.Communicate(speech_text, voice="hi-IN-MadhurNeural")
        await comm.save(scene_audio)
        dur = get_file_duration(scene_audio)

        ok = download_pexels_clip(sc.get("search", topic), raw_clip)
        if not ok or not os.path.exists(raw_clip):
            download_pexels_clip("cinematic", raw_clip)

        make_subtitle_png(sub_text, sub_png, width=1080, height=1920)

        # 1080p Full HD Encoding with exact audio-synced duration
        ff_cmd = (
            f"ffmpeg -y -t {dur} -stream_loop -1 -i \"{raw_clip}\" -i \"{sub_png}\" -i \"{scene_audio}\" "
            f"-filter_complex \"[0:v]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920[v0];"
            f"[v0][1:v]overlay=0:0[vout]\" -map \"[vout]\" -map 2:a -r 30 -c:v libx264 -preset veryfast "
            f"-crf 22 -c:a aac -threads 1 \"{seg_out}\""
        )
        subprocess.run(ff_cmd, shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if os.path.exists(seg_out):
            rendered_segments.append(seg_out)

    concat_list = "concat_list.txt"
    temp_files.append(concat_list)
    with open(concat_list, "w") as f:
        for seg in rendered_segments:
            f.write(f"file '{os.path.abspath(seg)}'\n")

    raw_merged = "raw_merged.mp4"
    final_video = "viral_reel_hd.mp4"
    temp_files.extend([raw_merged, final_video])

    subprocess.run(
        f"ffmpeg -y -f concat -safe 0 -i \"{concat_list}\" -c copy \"{raw_merged}\"",
        shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
    )

    # Mix 12% BGM for viral cinematic vibe
    ensure_assets()
    if os.path.exists(BGM_PATH):
        mix_cmd = (
            f"ffmpeg -y -i \"{raw_merged}\" -stream_loop -1 -i \"{BGM_PATH}\" "
            f"-filter_complex \"[1:a]volume=0.12[bgm];[0:a][bgm]amix=inputs=2:duration=first[aout]\" "
            f"-map 0:v -map \"[aout]\" -c:v copy -c:a aac \"{final_video}\""
        )
        subprocess.run(mix_cmd, shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    else:
        os.rename(raw_merged, final_video)

    gc.collect()
    full_script = "\n\n".join(full_script_lines)
    return full_script, final_video, temp_files

async def generate_reel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    topic = clean_for_speech(" ".join(context.args))
    if not topic:
        await update.message.reply_text("कृपया विषय लिखें। उदाहरण: `/reel बॉडी बनाने के 3 नियम`")
        return

    wait_msg = await update.message.reply_text("🎬 1080p Full HD वीडियो + सिंक सबटाइटल्स + BGM तैयार हो रहा है...")
    temp_files = []
    try:
        script, video, temp_files = await build_viral_reel(topic)
        await update.message.reply_text(f"📝 *स्क्रिप्ट:*\n\n{script}", parse_mode="Markdown")

        if os.path.exists(video) and os.path.getsize(video) > 50000:
            with open(video, "rb") as vf:
                await update.message.reply_video(video=vf, caption=f"🔥 1080p HD रील: {topic}")
        else:
            await update.message.reply_text("⚠️ वीडियो रेंडर नहीं हो सकी, पुनः प्रयास करें।")

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
    await update.message.reply_text("👑 Hermes Pro HD Studio सक्रिय है!\n\nकमांड भेजें:\n`/reel <विषय>`")

if __name__ == "__main__":
    ensure_assets()
    threading.Thread(target=run_http_server, daemon=True).start()
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("reel", generate_reel))
    app.run_polling()
