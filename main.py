import os
import gc
import re
import json
import threading
import subprocess
import requests
from http.server import HTTPServer, BaseHTTPRequestHandler
import edge_tts
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

class SimpleHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Hermes 60FPS Video Engine Active")

def run_http_server():
    port = int(os.environ.get("PORT", 10000))
    server = HTTPServer(("0.0.0.0", port), SimpleHandler)
    server.serve_forever()

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

FONT_PATH = "NotoSansDevanagari.ttf"
BGM_PATH = "bgm.mp3"

def ensure_assets():
    if not os.path.exists(FONT_PATH) or os.path.getsize(FONT_PATH) < 10000:
        font_url = "https://github.com/googlefonts/noto-fonts/raw/main/hinted/ttf/NotoSansDevanagari/NotoSansDevanagari-Bold.ttf"
        try:
            r = requests.get(font_url, timeout=15)
            if r.status_code == 200:
                with open(FONT_PATH, "wb") as f:
                    f.write(r.content)
        except Exception:
            pass

    if not os.path.exists(BGM_PATH) or os.path.getsize(BGM_PATH) < 5000:
        bgm_url = "https://cdn.pixabay.com/download/audio/2022/05/27/audio_1808fbf07a.mp3?filename=ambient-cinematic-112282.mp3"
        try:
            r = requests.get(bgm_url, timeout=15)
            if r.status_code == 200:
                with open(BGM_PATH, "wb") as f:
                    f.write(r.content)
        except Exception:
            pass

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
        models = ["gemini-1.5-flash", "gemini-1.5-pro"]
        headers = {
            "Content-Type": "application/json",
            "x-goog-api-key": GEMINI_API_KEY
        }
        prompt = f"""
Create a high-retention 3-scene Hindi Reel script about: '{topic}'.
Requirements:
- scene 1: Hook speech in Hindi + vivid English visual prompt for cinematic video generation.
- scene 2: Main core fact speech in Hindi + vivid English visual prompt.
- scene 3: Call to action in Hindi + dramatic closing English visual prompt.

Output ONLY valid JSON:
{{
  "scenes": [
    {{"speech": "पहला वाक्य हिंदी में", "visual_prompt": "cinematic hyperrealistic 8k video prompt"}},
    {{"speech": "दूसरा वाक्य हिंदी में", "visual_prompt": "cinematic hyperrealistic 8k video prompt"}},
    {{"speech": "तीसरा वाक्य हिंदी में", "visual_prompt": "cinematic hyperrealistic 8k video prompt"}}
  ]
}}
"""
        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": 0.4, "response_mime_type": "application/json"}
        }

        for m in models:
            try:
                url = f"https://generativelanguage.googleapis.com/v1beta/models/{m}:generateContent"
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
                continue

    en = re.sub(r'[^a-zA-Z0-9\s]', '', topic).strip() or "epic discovery"
    return [
        {"speech": f"क्या आप जानते हैं {topic} के बारे में यह चौंकाने वाला सच?", "visual_prompt": f"cinematic drone shot of {en}, dramatic lighting, 8k"},
        {"speech": f"इसके पीछे की सच्चाई जानकर आपके होश उड़ जाएंगे।", "visual_prompt": f"hyperrealistic close-up dynamic scene of {en}, masterpiece"},
        {"speech": "ऐसी ही अद्भुत जानकारियों के लिए हमें अभी फॉलो करें।", "visual_prompt": f"majestic atmospheric shot of {en}, cinematic"}
    ]

def get_file_duration(file_path):
    cmd = f"ffprobe -v error -show_entries format=duration -of default=noprint_wrappers=1:nokey=1 \"{file_path}\""
    try:
        out = subprocess.check_output(cmd, shell=True).decode().strip()
        return max(2.5, float(out))
    except Exception:
        return 4.0

def download_visual_clip(prompt, out_filename):
    clean_p = requests.utils.quote(prompt + ", vertical 9:16 portrait, smooth camera motion, cinematic, 8k")
    # टर्बो AI इंजन से फास्ट विज़ुअल लोड
    url = f"https://image.pollinations.ai/prompt/{clean_p}?width=576&height=1024&nologo=true&model=turbo"
    try:
        r = requests.get(url, timeout=14)
        if r.status_code == 200 and len(r.content) > 10000:
            with open(out_filename, "wb") as f:
                f.write(r.content)
            return True
    except Exception:
        pass
    return False

def make_srt_file(text, duration, srt_path):
    clean_s = clean_text(text)
    words = clean_s.split()
    if not words:
        words = [clean_s]

    chunk_size = 3
    chunks = [" ".join(words[i:i + chunk_size]) for i in range(0, len(words), chunk_size)]
    chunk_dur = duration / max(1, len(chunks))

    with open(srt_path, "w", encoding="utf-8") as f:
        for idx, chunk in enumerate(chunks):
            start_sec = idx * chunk_dur
            end_sec = min(duration, (idx + 1) * chunk_dur)

            sh, sm, ss = int(start_sec // 3600), int((start_sec % 3600) // 60), start_sec % 60
            eh, em, es = int(end_sec // 3600), int((end_sec % 3600) // 60), end_sec % 60

            start_str = f"{sh:02d}:{sm:02d}:{int(ss):02d},{int((ss % 1) * 1000):03d}"
            end_str = f"{eh:02d}:{em:02d}:{int(es):02d},{int((es % 1) * 1000):03d}"

            f.write(f"{idx + 1}\n{start_str} --> {end_str}\n{chunk}\n\n")

async def build_viral_reel(topic):
    ensure_assets()
    scenes = generate_script_safe(topic)
    rendered_segments = []
    temp_files = []
    full_script_lines = []

    W, H = 576, 1024

    for idx, sc in enumerate(scenes):
        speech_text = clean_text(sc.get("speech", ""))
        full_script_lines.append(speech_text)

        scene_audio = f"audio_{idx}.mp3"
        scene_img = f"visual_{idx}.jpg"
        scene_srt = f"sub_{idx}.srt"
        seg_out = f"seg_{idx}.mp4"
        temp_files.extend([scene_audio, scene_img, scene_srt, seg_out])

        # वॉइस को +15% पेसिंग दी गई
        try:
            comm = edge_tts.Communicate(speech_text, voice="hi-IN-MadhurNeural", rate="+15%")
            await comm.save(scene_audio)
        except Exception:
            comm = edge_tts.Communicate(speech_text, voice="hi-IN-SwaraNeural", rate="+15%")
            await comm.save(scene_audio)

        dur = get_file_duration(scene_audio)

        # विजुअल डाउनलोड
        vis_prompt = sc.get("visual_prompt", f"cinematic dynamic scene of {topic}")
        ok = download_visual_clip(vis_prompt, scene_img)
        if not ok or not os.path.exists(scene_img):
            fallback_img = f"ffmpeg -y -f lavfi -i color=c=0x111622:s={W}x{H}:d=1 -vframes 1 {scene_img}"
            subprocess.run(fallback_img, shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

        make_srt_file(speech_text, dur, scene_srt)

        # 60 FPS + डायनामिक मोशन + वर्ड सबटाइटल बर्न
        total_frames = int(dur * 60)
        sub_style = (
            "FontName=Noto Sans Devanagari,FontSize=18,PrimaryColour=&H0014EBFF,"
            "OutlineColour=&H00000000,BorderStyle=1,Outline=2,Alignment=2,MarginV=120"
        )

        filter_complex = (
            f"[0:v]scale=-2:{H}*2,zoompan=z='min(zoom+0.0008,1.20)':d={total_frames}:x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s={W}x{H}:fps=60,"
            f"subtitles='{scene_srt}':force_style='{sub_style}'[vout]"
        )

        ff_cmd = (
            f"ffmpeg -y -loop 1 -t {dur} -i \"{scene_img}\" -i \"{scene_audio}\" "
            f"-filter_complex \"{filter_complex}\" -map \"[vout]\" -map 1:a -r 60 -c:v libx264 "
            f"-preset ultrafast -threads 1 -c:a aac \"{seg_out}\""
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
    final_video = "viral_reel_60fps.mp4"
    temp_files.extend([raw_merged, final_video])

    subprocess.run(
        f"ffmpeg -y -f concat -safe 0 -i \"{concat_list}\" -c copy \"{raw_merged}\"",
        shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
    )

    if os.path.exists(BGM_PATH):
        mix_cmd = (
            f"ffmpeg -y -i \"{raw_merged}\" -stream_loop -1 -i \"{BGM_PATH}\" "
            f"-filter_complex \"[1:a]volume=0.10[bgm];[0:a][bgm]amix=inputs=2:duration=first[aout]\" "
            f"-map 0:v -map \"[aout]\" -r 60 -c:v copy -c:a aac \"{final_video}\""
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
        await update.message.reply_text("कृपया विषय लिखें। उदाहरण: `/reel ब्रह्मांड के अनसुलझे रहस्य`")
        return

    wait_msg = await update.message.reply_text(f"⚡ '{topic}' पर 60 FPS रील तैयार की जा रही है...")
    temp_files = []
    try:
        script, video, temp_files = await build_viral_reel(topic)
        await update.message.reply_text(f"📝 *स्क्रिप्ट:*\n\n{script}", parse_mode="Markdown")

        if os.path.exists(video) and os.path.getsize(video) > 40000:
            with open(video, "rb") as vf:
                await update.message.reply_video(video=vf, caption=f"🔥 60 FPS HD रील: {topic}")
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
    await update.message.reply_text("👑 Hermes 60FPS AI Studio सक्रिय है!\n\nरील बनाने के लिए भेजें:\n`/reel <विषय>`")

async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("✅ Hermes 60FPS Studio लाइव है और तैयार है!")

if __name__ == "__main__":
    ensure_assets()
    threading.Thread(target=run_http_server, daemon=True).start()
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("status", status))
    app.add_handler(CommandHandler("reel", generate_reel))
    app.run_polling()
