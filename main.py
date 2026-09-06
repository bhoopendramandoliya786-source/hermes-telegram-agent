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
Create an extremely engaging and viral 3-scene YouTube Shorts/Reels script in Hindi about: '{topic}'.
Requirements:
- scene 1: Powerful Hook line in Hindi + 2-3 words punchy subtitle + photorealistic English prompt for image.
- scene 2: Mindblowing fact in Hindi + 2-3 words punchy subtitle + detailed photorealistic English prompt.
- scene 3: Call to action in Hindi + 2-3 words punchy subtitle + cinematic English prompt.

Return valid JSON:
{{
  "scenes": [
    {{"speech": "पहला वाक्य हिंदी में", "sub": "संक्षिप्त सबटाइटल", "image_prompt": "cinematic photorealistic english description"}},
    {{"speech": "दूसरा वाक्य हिंदी में", "sub": "संक्षिप्त सबटाइटल", "image_prompt": "cinematic photorealistic english description"}},
    {{"speech": "तीसरा वाक्य हिंदी में", "sub": "फॉलो करें", "image_prompt": "cinematic photorealistic english description"}}
  ]
}}
"""
        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {
                "temperature": 0.4,
                "response_mime_type": "application/json"
            }
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
            except Exception as e:
                print(f"Gemini {m} error: {e}")
                continue

    en = re.sub(r'[^a-zA-Z0-9\s]', '', topic).strip() or "epic discovery"
    return [
        {"speech": f"क्या आप जानते हैं {topic} के बारे में यह चौंकाने वाला सच?", "sub": "अनोखा सच", "image_prompt": f"hyperrealistic cinematic scene of {en}, dramatic atmospheric lighting, 8k resolution, photorealistic"},
        {"speech": f"इसके पीछे की सच्चाई जानकर आपके होश उड़ जाएंगे।", "sub": "हैरान करने वाला तथ्य", "image_prompt": f"detailed close-up cinematic shot of {en}, unreal engine 5, masterpiece"},
        {"speech": "ऐसी ही अद्भुत जानकारियों के लिए अभी फॉलो करें।", "sub": "अभी फॉलो करें", "image_prompt": f"epic majestic atmospheric shot of {en}, glorious cinematic lighting"}
    ]

def get_file_duration(file_path):
    cmd = f"ffprobe -v error -show_entries format=duration -of default=noprint_wrappers=1:nokey=1 \"{file_path}\""
    try:
        out = subprocess.check_output(cmd, shell=True).decode().strip()
        return max(2.5, float(out))
    except Exception:
        return 4.0

def download_ai_image(prompt, out_filename):
    clean_p = requests.utils.quote(prompt + ", 8k resolution, cinematic lighting, hyper-realistic, dramatic, vertical 9:16 portrait orientation")
    url = f"https://image.pollinations.ai/prompt/{clean_p}?width=720&height=1280&nologo=true&model=turbo"
    try:
        r = requests.get(url, timeout=14)
        if r.status_code == 200 and len(r.content) > 10000:
            with open(out_filename, "wb") as f:
                f.write(r.content)
            return True
    except Exception as e:
        print(f"Image error: {e}")
    return False

def make_subtitle_png(text, png_filename, width=720, height=1280):
    ensure_assets()
    img = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    try:
        font = ImageFont.truetype(FONT_PATH, 52)
    except Exception:
        font = ImageFont.load_default()

    clean_sub = clean_text(text)
    words = clean_sub.split()
    lines, cur = [], []
    for w in words:
        cur.append(w)
        if len(" ".join(cur)) > 11:
            lines.append(" ".join(cur[:-1]))
            cur = [w]
    if cur:
        lines.append(" ".join(cur))

    y = int(height * 0.68)
    for line in lines:
        bbox = draw.textbbox((0, 0), line, font=font)
        tw = bbox[2] - bbox[0]
        th = bbox[3] - bbox[1]
        x = (width - tw) // 2
        
        # इंस्टाग्राम स्टाइल: ब्राइट येलो टेक्स्ट और थिक ब्लैक बॉर्डर
        stroke_w = 4
        draw.text((x, y), line, font=font, fill=(255, 235, 20, 255),
                  stroke_width=stroke_w, stroke_fill=(0, 0, 0, 255))
        y += th + 18
        
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
        scene_img = f"img_{idx}.jpg"
        sub_png = f"sub_{idx}.png"
        seg_out = f"seg_{idx}.mp4"
        temp_files.extend([scene_audio, scene_img, sub_png, seg_out])

        # वॉइस को +15% तेज़ किया ताकि रील सुस्त न लगे
        try:
            comm = edge_tts.Communicate(speech_text, voice="hi-IN-MadhurNeural", rate="+15%")
            await comm.save(scene_audio)
        except Exception:
            comm = edge_tts.Communicate(speech_text, voice="hi-IN-SwaraNeural", rate="+15%")
            await comm.save(scene_audio)

        dur = get_file_duration(scene_audio)

        img_prompt = sc.get("image_prompt", f"cinematic scene of {topic}")
        ok = download_ai_image(img_prompt, scene_img)
        if not ok or not os.path.exists(scene_img):
            fallback_img = Image.new("RGB", (W, H), (15, 20, 28))
            fallback_img.save(scene_img)

        make_subtitle_png(sub_text, sub_png, width=W, height=H)

        total_frames = int(dur * 24)
        # स्मूथ ज़ूम-इन मोशन (Ken Burns Effect)
        filter_complex = (
            f"[0:v]scale=-2:{H}*2,zoompan=z='min(zoom+0.0015,1.25)':d={total_frames}:x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s={W}x{H}:fps=24[bg];"
            f"[bg][1:v]overlay=0:0[vout]"
        )

        ff_cmd = (
            f"ffmpeg -y -loop 1 -t {dur} -i \"{scene_img}\" -i \"{sub_png}\" -i \"{scene_audio}\" "
            f"-filter_complex \"{filter_complex}\" -map \"[vout]\" -map 2:a -r 24 -c:v libx264 "
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
        await update.message.reply_text("कृपया विषय लिखें। उदाहरण: `/reel शेर जंगल का राजा क्यों है`")
        return

    wait_msg = await update.message.reply_text(f"⚡ '{topic}' पर HD रील तैयार की जा रही है...")
    temp_files = []
    try:
        script, video, temp_files = await build_viral_reel(topic)
        await update.message.reply_text(f"📝 *स्क्रिप्ट:*\n\n{script}", parse_mode="Markdown")

        if os.path.exists(video) and os.path.getsize(video) > 40000:
            with open(video, "rb") as vf:
                await update.message.reply_video(video=vf, caption=f"🔥 HD रील: {topic}")
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
    await update.message.reply_text("👑 Hermes Pro AI Studio सक्रिय है!\n\nकमांड भेजें:\n`/reel <विषय>`")

async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("✅ Hermes Studio बिल्कुल ठीक चल रहा है और रील बनाने के लिए तैयार है!")

if __name__ == "__main__":
    ensure_assets()
    threading.Thread(target=run_http_server, daemon=True).start()
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("status", status))
    app.add_handler(CommandHandler("reel", generate_reel))
    app.run_polling()
