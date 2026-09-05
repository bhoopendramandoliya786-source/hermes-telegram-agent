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
    if GEMINI_API_KEY:
        models = ["gemini-1.5-flash", "gemini-1.5-pro"]
        system_instruction = (
            "You are a professional YouTube Shorts scriptwriter. "
            "Write engaging, accurate, topic-specific Hindi content. "
            "Return purely valid JSON with 3 scenes."
        )
        prompt = f"""
Create a 3-scene viral video script for the topic: '{topic}'.
Respond ONLY in this exact JSON structure (no markdown, no extra text):
{{
  "scenes": [
    {{"speech": "पहला दृश्य: विषय से जुड़ा एक चौंकाने वाला तथ्य हिंदी में", "sub": "संक्षिप्त हुक सबटाइटल", "search": "highly relevant english visual query for pexels"}},
    {{"speech": "दूसरा दृश्य: इस विषय की मुख्य और दिलचस्प जानकारी हिंदी में", "sub": "मुख्य जानकारी सबटाइटल", "search": "detailed english visual query for pexels"}},
    {{"speech": "तीसरा दृश्य: एक प्रेरणादायक अंत या कॉल टू एक्शन हिंदी में", "sub": "अभी सब्सक्राइब करें", "search": "relevant dramatic closing cinematic footage"}}
  ]
}}
"""
        for m in models:
            try:
                url = f"https://generativelanguage.googleapis.com/v1beta/models/{m}:generateContent?key={GEMINI_API_KEY}"
                payload = {
                    "contents": [{"parts": [{"text": prompt}]}],
                    "generationConfig": {"temperature": 0.5}
                }
                res = requests.post(url, json=payload, timeout=12)
                if res.status_code == 200:
                    data = res.json()
                    raw = data['candidates'][0]['content']['parts'][0]['text']
                    raw = re.sub(r'^```json\s*', '', raw.strip())
                    raw = re.sub(r'```$', '', raw.strip())
                    match = re.search(r'\{.*\}', raw, re.DOTALL)
                    parsed = json.loads(match.group(0)) if match else json.loads(raw)
                    if "scenes" in parsed and len(parsed["scenes"]) >= 2:
                        return parsed["scenes"]
            except Exception as e:
                print(f"Gemini API issue on {m}: {e}")
                continue

    # अगर API से रिस्पॉन्स न मिले तो विषय आधारित ऑटो-स्क्रिप्ट
    english_query = re.sub(r'[^a-zA-Z0-9\s]', '', topic).strip() or "cinematic ocean nature"
    return [
        {"speech": f"क्या आप जानते हैं {topic} की सबसे अनोखी और अनसुनी कहानी?", "sub": f"{topic}", "search": f"{english_query} nature cinematic"},
        {"speech": f"गहराई में जाने पर {topic} से जुड़े कई ऐसे रहस्य सामने आते हैं जो हैरान कर देते हैं।", "sub": "अद्भुत रहस्य", "search": f"{english_query} underwater mystery cinematic"},
        {"speech": "अगर आपको यह तथ्य पसंद आया तो वीडियो को लाइक और सब्सक्राइब जरूर करें।", "sub": "सब्सक्राइब करें", "search": "deep blue sea nature cinematic"}
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
    url = f"https://api.pexels.com/videos/search?query={clean_q}&orientation=portrait&per_page=8"
    headers = {"Authorization": PEXELS_API_KEY}
    try:
        res = requests.get(url, headers=headers, timeout=15).json()
        videos = res.get("videos", [])
        if not videos:
            alt_url = "https://api.pexels.com/videos/search?query=ocean+nature+cinematic&orientation=portrait&per_page=8"
            videos = requests.get(alt_url, headers=headers, timeout=15).json().get("videos", [])
        
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

async def build_viral_reel(topic):
    ensure_assets()
    scenes = generate_script_safe(topic)
    rendered_segments = []
    temp_files = []
    full_script_lines = []

    W, H = 720, 1280

    for idx, sc in enumerate(scenes):
        speech_text = clean_text(sc.get("speech", ""))
        sub_text = clean_text(sc.get("sub", speech_text))
        full_script_lines.append(speech_text)

        scene_audio = f"audio_{idx}.mp3"
        raw_clip = f"raw_{idx}.mp4"
        seg_out = f"seg_{idx}.mp4"
        temp_files.extend([scene_audio, raw_clip, seg_out])

        try:
            comm = edge_tts.Communicate(speech_text, voice="hi-IN-SwaraNeural")
            await comm.save(scene_audio)
        except Exception:
            comm = edge_tts.Communicate(speech_text, voice="hi-IN-MadhurNeural")
            await comm.save(scene_audio)

        dur = get_file_duration(scene_audio)

        search_query = sc.get("search", topic)
        ok = download_pexels_clip(search_query, raw_clip, scene_index=idx)
        if not ok or not os.path.exists(raw_clip):
            download_pexels_clip(f"{topic} cinematic", raw_clip, scene_index=idx)

        # सबटाइटल टेक्स्ट को फ़ाइल में सेव करना (विशेष चिह्नों से बचने के लिए)
        sub_txt_file = f"sub_{idx}.txt"
        temp_files.append(sub_txt_file)
        with open(sub_txt_file, "w", encoding="utf-8") as tf:
            tf.write(sub_text)

        # FFmpeg drawtext: बिना किसी डिब्बे के साफ़ देवनागरी फॉन्ट रेंडरिंग
        font_abs = os.path.abspath(FONT_PATH).replace("\\", "/").replace(":", "\\:")
        sub_txt_abs = os.path.abspath(sub_txt_file).replace("\\", "/").replace(":", "\\:")
        
        filter_complex = (
            f"[0:v]scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H}[scaled];"
            f"[scaled]drawtext=fontfile='{font_abs}':textfile='{sub_txt_abs}':reload=1:"
            f"fontcolor=yellow:fontsize=46:box=1:boxcolor=black@0.75:boxborderw=14:"
            f"x=(w-text_w)/2:y=h*0.75[vout]"
        )

        ff_cmd = (
            f"ffmpeg -y -t {dur} -stream_loop -1 -i \"{raw_clip}\" -i \"{scene_audio}\" "
            f"-filter_complex \"{filter_complex}\" -map \"[vout]\" -map 1:a -r 24 -c:v libx264 "
            f"-preset ultrafast -bufsize 1024k -threads 1 -c:a aac \"{seg_out}\""
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
            f"-filter_complex \"[1:a]volume=0.12[bgm];[0:a][bgm]amix=inputs=2:duration=first[aout]\" "
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
        await update.message.reply_text("कृपया विषय लिखें। उदाहरण: `/reel समुद्र के अनसुलझे रहस्य`")
        return

    wait_msg = await update.message.reply_text(f"⚡ '{topic}' पर HD रील बनाई जा रही है, कृपया 1 मिनट रुकें...")
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
