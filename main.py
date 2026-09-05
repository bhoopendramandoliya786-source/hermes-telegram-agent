import os
import gc
import re
import json
import threading
import subprocess
import requests
from http.server import HTTPServer, BaseHTTPRequestHandler
from PIL import Image, ImageDraw, ImageFont
import edge_tts
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

class SimpleHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Hermes Video Engine Running")

def run_http_server():
    port = int(os.environ.get("PORT", 10000))
    server = HTTPServer(("0.0.0.0", port), SimpleHandler)
    server.serve_forever()

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
PEXELS_API_KEY = os.getenv("PEXELS_API_KEY", "")

FONT_PATH = "NotoSansDevanagari.ttf"
BGM_PATH = "bgm.mp3"

def ensure_assets():
    if not os.path.exists(FONT_PATH) or os.path.getsize(FONT_PATH) < 10000:
        font_url = "https://github.com/googlefonts/noto-fonts/raw/main/hinted/ttf/NotoSansDevanagari/NotoSansDevanagari-Bold.ttf"
        try:
            r = requests.get(font_url, timeout=20)
            if r.status_code == 200:
                with open(FONT_PATH, "wb") as f:
                    f.write(r.content)
        except Exception:
            pass

    if not os.path.exists(BGM_PATH) or os.path.getsize(BGM_PATH) < 5000:
        bgm_url = "https://cdn.pixabay.com/download/audio/2022/05/27/audio_1808fbf07a.mp3?filename=ambient-cinematic-112282.mp3"
        try:
            r = requests.get(bgm_url, timeout=20)
            if r.status_code == 200:
                with open(BGM_PATH, "wb") as f:
                    f.write(r.content)
        except Exception:
            pass

def clean_text(text):
    text = re.sub(r'[*_~`#\[\]\(\)\<\>\"\'\\]', ' ', text)
    return re.sub(r'\s+', ' ', text).strip()

def generate_script_safe(topic):
    # Gemini 1.5 Flash API कॉल
    if GEMINI_API_KEY:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={GEMINI_API_KEY}"
        prompt = f"""
You are an expert YouTube Shorts and Instagram Reels scriptwriter.
Topic: '{topic}'

Write an engaging, highly accurate 3-scene video script specifically about '{topic}'.
Provide 3 scenes where each scene has:
- 'speech': 1 single compelling Hindi sentence specifically explaining the topic.
- 'sub': 2-4 Hindi words summarizing the scene (no long sentences).
- 'search': 2-3 English keywords for Pexels stock video footage directly matching the visual of the topic (e.g., if topic is remedies, search 'natural herbal medicine'; if rocket, search 'space rocket launch').

Respond ONLY with valid JSON in this exact structure:
{{
  "scenes": [
    {{"speech": "पहला वाक्य हिंदी में", "sub": "संक्षिप्त सबटाइटल", "search": "accurate english query"}},
    {{"speech": "दूसरा वाक्य हिंदी में", "sub": "संक्षिप्त सबटाइटल", "search": "accurate english query"}},
    {{"speech": "तीसरा वाक्य हिंदी में", "sub": "सब्सक्राइब करें", "search": "accurate english query"}}
  ]
}}
"""
        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": 0.4}
        }
        try:
            res = requests.post(url, json=payload, timeout=14)
            if res.status_code == 200:
                data = res.json()
                raw = data['candidates'][0]['content']['parts'][0]['text']
                raw = re.sub(r'```json', '', raw)
                raw = re.sub(r'```', '', raw).strip()
                match = re.search(r'\{.*\}', raw, re.DOTALL)
                if match:
                    parsed = json.loads(match.group(0))
                    if "scenes" in parsed and len(parsed["scenes"]) >= 3:
                        return parsed["scenes"]
            else:
                print(f"Gemini API Error: {res.status_code} - {res.text}")
        except Exception as e:
            print(f"Gemini request failed: {e}")

    # यदि API किसी कारण से न चले तो विषय से जुड़ा सटीक फॉलबैक
    clean_kw = re.sub(r'[^a-zA-Z0-9\s]', '', topic).strip() or "cinematic mystery"
    return [
        {"speech": f"क्या आप {topic} के बारे में यह चौंकाने वाला सच जानते हैं?", "sub": "अनोखा सच", "search": f"{clean_kw} nature"},
        {"speech": f"यह विषय जितना साधारण दिखता है, असल में इसके पीछे का विज्ञान उतना ही गहरा है।", "sub": "गहरा विज्ञान", "search": f"{clean_kw} science"},
        {"speech": "ऐसी ही रोचक जानकारियों के लिए हमारे चैनल को अभी फॉलो और सब्सक्राइब करें।", "sub": "सब्सक्राइब करें", "search": "subscribe follow cinematic"}
    ]

def get_file_duration(file_path):
    cmd = f"ffprobe -v error -show_entries format=duration -of default=noprint_wrappers=1:nokey=1 \"{file_path}\""
    try:
        out = subprocess.check_output(cmd, shell=True).decode().strip()
        return max(2.5, float(out))
    except Exception:
        return 4.5

def download_pexels_clip(query, out_filename, scene_index=0):
    if not PEXELS_API_KEY:
        return False
    clean_q = requests.utils.quote(query)
    url = f"https://api.pexels.com/videos/search?query={clean_q}&orientation=portrait&per_page=10"
    headers = {"Authorization": PEXELS_API_KEY}
    try:
        res = requests.get(url, headers=headers, timeout=14).json()
        videos = res.get("videos", [])
        if not videos:
            alt_url = "https://api.pexels.com/videos/search?query=cinematic+nature&orientation=portrait&per_page=10"
            videos = requests.get(alt_url, headers=headers, timeout=14).json().get("videos", [])
        
        if videos:
            chosen_vid = videos[scene_index % len(videos)]
            files = [f for f in chosen_vid.get("video_files", []) if f.get("height", 0) > f.get("width", 0)]
            target = files[0]["link"] if files else chosen_vid["video_files"][0]["link"]
            with requests.get(target, stream=True, timeout=25) as r:
                with open(out_filename, "wb") as f:
                    for chunk in r.iter_content(chunk_size=1024*256):
                        f.write(chunk)
            return True
    except Exception as e:
        print(f"Pexels error: {e}")
    return False

def make_subtitle_png(text, png_filename, width=720, height=1280):
    ensure_assets()
    img = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    try:
        font = ImageFont.truetype(FONT_PATH, 44)
    except Exception:
        font = ImageFont.load_default()

    # सबटाइटल को 2-3 शब्दों में ही रखना ताकि कोई डिब्बा या ओवरलैप न बने
    clean_sub = clean_text(text)
    words = clean_sub.split()
    lines, cur = [], []
    for w in words:
        cur.append(w)
        if len(" ".join(cur)) > 10:
            lines.append(" ".join(cur[:-1]))
            cur = [w]
    if cur:
        lines.append(" ".join(cur))

    y = int(height * 0.74)
    for line in lines:
        bbox = draw.textbbox((0, 0), line, font=font)
        tw = bbox[2] - bbox[0]
        th = bbox[3] - bbox[1]
        x = (width - tw) // 2
        pad_x, pad_y = 16, 8
        draw.rounded_rectangle([x - pad_x, y - pad_y, x + tw + pad_x, y + th + pad_y], radius=10, fill=(0, 0, 0, 225))
        draw.text((x, y), line, fill=(255, 235, 20, 255), font=font)
        y += th + 20
    img.save(png_filename)
    img.close()

async def build_viral_reel(topic):
    ensure_assets()
    scenes = generate_script_safe(topic)
    rendered_segments = []
    temp_files = []
    full_script_lines = []

    W, H = 720, 1280

    for idx, sc in enumerate(scenes):
        speech_text = clean_text(sc.get("speech", ""))
        sub_text = clean_text(sc.get("sub", speech_text[:12]))
        full_script_lines.append(speech_text)

        scene_audio = f"audio_{idx}.mp3"
        raw_clip = f"raw_{idx}.mp4"
        sub_png = f"sub_{idx}.png"
        seg_out = f"seg_{idx}.mp4"
        temp_files.extend([scene_audio, raw_clip, sub_png, seg_out])

        # वॉइस जनरेशन
        try:
            comm = edge_tts.Communicate(speech_text, voice="hi-IN-SwaraNeural")
            await comm.save(scene_audio)
        except Exception:
            comm = edge_tts.Communicate(speech_text, voice="hi-IN-MadhurNeural")
            await comm.save(scene_audio)

        dur = get_file_duration(scene_audio)

        # सटीक विजुअल डाउनलोड
        search_query = sc.get("search", topic)
        ok = download_pexels_clip(search_query, raw_clip, scene_index=idx)
        if not ok or not os.path.exists(raw_clip):
            download_pexels_clip("cinematic emotion", raw_clip, scene_index=idx)

        # सबटाइटल इमेज
        make_subtitle_png(sub_text, sub_png, width=W, height=H)

        # FFmpeg सेगमेंट एन्कोडिंग
        ff_cmd = (
            f"ffmpeg -y -t {dur} -stream_loop -1 -i \"{raw_clip}\" -i \"{sub_png}\" -i \"{scene_audio}\" "
            f"-filter_complex \"[0:v]scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H}[v0];"
            f"[v0][1:v]overlay=0:0[vout]\" -map \"[vout]\" -map 2:a -r 24 -c:v libx264 -preset ultrafast "
            f"-bufsize 1024k -threads 1 -c:a aac \"{seg_out}\""
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

    if os.path.exists(BGM_PATH):
        mix_cmd = (
            f"ffmpeg -y -i \"{raw_merged}\" -stream_loop -1 -i \"{BGM_PATH}\" "
            f"-filter_complex \"[1:a]volume=0.10[bgm];[0:a][bgm]amix=inputs=2:duration=first[aout]\" "
            f"-map 0:v -map \"[aout]\" -c:v copy -c:a aac \"{final_video}\""
        )
        subprocess.run(mix_cmd, shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    else:
        if os.path.exists(raw_merged):
            os.rename(raw_merged, final_video)

    gc.collect()
    full_script = "\n\n".join(full_script_lines)
    return full_script, final_video, temp_files

async def generate_reel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    topic = clean_text(" ".join(context.args))
    if not topic:
        await update.message.reply_text("कृपया विषय लिखें। उदाहरण: `/reel space rocket launch`")
        return

    wait_msg = await update.message.reply_text(f"⚡ '{topic}' पर HD रील तैयार की जा रही है, कृपया 1 मिनट रुकें...")
    temp_files = []
    try:
        script, video, temp_files = await build_viral_reel(topic)
        await update.message.reply_text(f"📝 *स्क्रिप्ट:*\n\n{script}", parse_mode="Markdown")

        if os.path.exists(video) and os.path.getsize(video) > 50000:
            with open(video, "rb") as vf:
                await update.message.reply_video(video=vf, caption=f"🔥 HD रील तैयार: {topic}")
        else:
            await update.message.reply_text("⚠️ वीडियो तैयार नहीं हो सका, पुनः प्रयास करें।")

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
        try:
            await wait_msg.delete()
        except Exception:
            pass

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("👑 Hermes Pro HD Studio सक्रिय है!\n\nकमांड भेजें:\n`/reel <विषय>`")

if __name__ == "__main__":
    ensure_assets()
    threading.Thread(target=run_http_server, daemon=True).start()
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("reel", generate_reel))
    app.run_polling()
