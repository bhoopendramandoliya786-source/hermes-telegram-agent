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

FONT_PATH = "NotoSansDevanagari-Bold.ttf"
BGM_PATH = "bgm.mp3"

def ensure_assets():
    if not os.path.exists(FONT_PATH) or os.path.getsize(FONT_PATH) < 20000:
        font_url = "https://raw.githubusercontent.com/googlefonts/noto-fonts/main/hinted/ttf/NotoSansDevanagari/NotoSansDevanagari-Bold.ttf"
        try:
            r = requests.get(font_url, timeout=25)
            if r.status_code == 200 and len(r.content) > 20000:
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

def generate_script_dynamic(raw_topic):
    topic = clean_user_prompt(raw_topic)
    if not GEMINI_API_KEY:
        raise Exception("GEMINI_API_KEY Render Environment में सेट नहीं है!")

    headers = {"Content-Type": "application/json"}
    prompt = f"""
Write an extremely engaging 3-scene Hindi YouTube Shorts / Reel script about the topic: '{topic}'.
MANDATORY RULES:
- Provide REAL, SPECIFIC, UNIQUE facts about '{topic}'.
- Strictly DO NOT use generic filler sentences like 'क्या आप जानते हैं' or 'इसके पीछे का सच'.
- Scene 1: Direct curiosity hook about '{topic}'.
- Scene 2: The most shocking fact or mechanism about '{topic}'.
- Scene 3: Practical impact or conclusion.
- Visual prompts MUST directly describe '{topic}' visually in detailed cinematic English.

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
        raise Exception(f"Gemini API Error ({res.status_code}): {res.text[:150]}")

    data = res.json()
    out_text = data['candidates'][0]['content']['parts'][0]['text']
    parsed = json.loads(re.search(r'\{.*\}', out_text, re.DOTALL).group(0))
    return parsed["scenes"]

def get_file_duration(file_path):
    cmd = f"ffprobe -v error -show_entries format=duration -of default=noprint_wrappers=1:nokey=1 \"{file_path}\""
    try:
        out = subprocess.check_output(cmd, shell=True).decode().strip()
        return max(2.5, float(out))
    except Exception:
        return 4.0

def download_visual(prompt, out_filename, topic, idx):
    clean_p = requests.utils.quote(f"{prompt}, vertical 9:16 portrait orientation, cinematic, photorealistic, 8k")
    url = f"https://image.pollinations.ai/prompt/{clean_p}?width=576&height=1024&nologo=true&model=turbo"
    try:
        r = requests.get(url, timeout=25)
        if r.status_code == 200 and len(r.content) > 10000:
            with open(out_filename, "wb") as f:
                f.write(r.content)
            return True
    except Exception:
        pass

    try:
        clean_topic = re.sub(r'[^a-zA-Z]', '', topic) or "cinematic"
        backup_url = f"https://images.unsplash.com/photo-1518837695005-2083093ee35b?auto=format&fit=crop&w=576&h=1024&q=80"
        r2 = requests.get(backup_url, timeout=12)
        if r2.status_code == 200 and len(r2.content) > 10000:
            with open(out_filename, "wb") as f:
                f.write(r2.content)
            return True
    except Exception:
        pass

    return False

def make_full_subtitle(text, png_path, width=576, height=1024):
    ensure_assets()
    img = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    
    font = None
    if os.path.exists(FONT_PATH):
        try:
            font = ImageFont.truetype(FONT_PATH, 28)
        except Exception:
            pass
    if font is None:
        font = ImageFont.load_default()

    clean_s = clean_text(text)
    words = clean_s.split()
    lines, cur = [], []
    for w in words:
        cur.append(w)
        if len(" ".join(cur)) > 12:
            lines.append(" ".join(cur[:-1]))
            cur = [w]
    if cur:
        lines.append(" ".join(cur))

    # सबटाइटल स्क्रीन के 60% हिस्से पर (नीचे से कटने का कोई खतरा नहीं)
    y = int(height * 0.60)
    for line in lines:
        bbox = draw.textbbox((0, 0), line, font=font)
        tw = bbox[2] - bbox[0]
        th = bbox[3] - bbox[1]
        x = (width - tw) // 2

        pad_x, pad_y = 10, 5
        draw.rounded_rectangle([x - pad_x, y - pad_y, x + tw + pad_x, y + th + pad_y], radius=8, fill=(0, 0, 0, 210))
        draw.text((x, y), line, font=font, fill=(255, 235, 20, 255))
        y += th + 10

    img.save(png_path)
    img.close()

async def build_viral_reel(topic, update: Update):
    ensure_assets()
    
    scenes = generate_script_dynamic(topic)
    script_text = "\n\n".join([f"🎬 *सीन {i+1}:* {s['speech']}" for i, s in enumerate(scenes)])
    await update.message.reply_text(f"📝 *ओरिजिनल स्क्रिप्ट:*\n\n{script_text}", parse_mode="Markdown")

    rendered_segments = []
    temp_files = []
    W, H = 576, 1024

    for idx, sc in enumerate(scenes):
        speech_text = clean_text(sc.get("speech", ""))
        scene_audio = f"aud_{idx}.mp3"
        scene_img = f"vis_{idx}.jpg"
        sub_png = f"sub_{idx}.png"
        seg_out = f"seg_{idx}.mp4"
        temp_files.extend([scene_audio, scene_img, sub_png, seg_out])

        try:
            comm = edge_tts.Communicate(speech_text, voice="hi-IN-MadhurNeural", rate="+15%")
            await comm.save(scene_audio)
        except Exception:
            comm = edge_tts.Communicate(speech_text, voice="hi-IN-SwaraNeural", rate="+15%")
            await comm.save(scene_audio)

        dur = get_file_duration(scene_audio)
        total_frames = int(dur * 30)

        vis_prompt = sc.get("visual_prompt", f"{topic} dynamic cinematic view")
        ok = download_visual(vis_prompt, scene_img, topic, idx)
        if not ok or not os.path.exists(scene_img):
            fallback_img = Image.new("RGB", (W, H), (15, 28, 45))
            fallback_img.save(scene_img)

        make_full_subtitle(speech_text, sub_png, width=W, height=H)

        # मेमोरी-सेफ़ ज़ूम: 512MB RAM पर बिना क्रैश के स्मूथ मोशन
        filter_complex = (
            f"[0:v]scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},"
            f"zoompan=z='min(zoom+0.0008,1.10)':d={total_frames}:x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s={W}x{H}:fps=30[vbg];"
            f"[vbg][1:v]overlay=0:0[vout]"
        )

        ff_cmd = (
            f"ffmpeg -y -loop 1 -t {dur} -i \"{scene_img}\" -i \"{sub_png}\" -i \"{scene_audio}\" "
            f"-filter_complex \"{filter_complex}\" -map \"[vout]\" -map 2:a -r 30 -c:v libx264 "
            f"-preset ultrafast -bufsize 256k -threads 1 -c:a aac \"{seg_out}\""
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
            f"-map 0:v -map \"[aout]\" -r 30 -c:v copy -c:a aac \"{final_video}\""
        )
        subprocess.run(mix_cmd, shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    else:
        if os.path.exists(raw_merged):
            os.rename(raw_merged, final_video)

    gc.collect()
    return final_video, temp_files

async def generate_reel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    topic = clean_text(" ".join(context.args))
    if not topic:
        await update.message.reply_text("कृपया विषय लिखें। उदाहरण: `/reel वायुमंडल का रहस्य`")
        return

    wait_msg = await update.message.reply_text(f"⚡ '{topic}' पर रील तैयार की जा रही है... पूरा बनते ही वीडियो आ जाएगी!")
    temp_files = []
    try:
        video, temp_files = await build_viral_reel(topic, update)

        if os.path.exists(video) and os.path.getsize(video) > 40000:
            with open(video, "rb") as vf:
                await update.message.reply_video(video=vf, caption=f"🔥 {topic}")
        else:
            await update.message.reply_text("⚠️ वीडियो रेंडर अधूरा रह गया, कृपया दोबारा कमांड भेजें।")

    except Exception as e:
        await update.message.reply_text(f"❌ *सिस्टम एरर:*\n`{str(e)}`", parse_mode="Markdown")
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
    await update.message.reply_text("👑 Hermes AI Reel Studio सक्रिय है!\n\nरील बनाने के लिए भेजें:\n`/reel <विषय>`")

if __name__ == "__main__":
    ensure_assets()
    threading.Thread(target=run_http_server, daemon=True).start()
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("reel", generate_reel))
    app.run_polling()
