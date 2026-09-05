import os
import gc
import json
import random
import threading
import urllib.parse
import requests
from http.server import HTTPServer, BaseHTTPRequestHandler
from PIL import Image, ImageDraw, ImageFont
import google.generativeai as genai
import edge_tts
from moviepy import AudioFileClip, ImageClip, concatenate_videoclips
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

class SimpleHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Hermes AI Studio Active")

def run_http_server():
    port = int(os.environ.get("PORT", 10000))
    server = HTTPServer(("0.0.0.0", port), SimpleHandler)
    server.serve_forever()

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel("models/gemini-3.6-flash")

def download_ai_image(prompt_desc, filename):
    clean_prompt = f"cinematic dramatic 8k vertical portrait: {prompt_desc}"
    encoded = urllib.parse.quote(clean_prompt)
    url = f"https://image.pollinations.ai/prompt/{encoded}?width=540&height=960&nologo=true&seed={random.randint(1, 99999)}"
    try:
        r = requests.get(url, timeout=25)
        if r.status_code == 200:
            with open(filename, "wb") as f:
                f.write(r.content)
            return True
    except Exception as e:
        print(f"Image generation error: {e}")
    return False

def add_subtitles_to_image(img_path, subtitle_text):
    base = Image.open(img_path).convert("RGBA")
    w, h = base.size
    overlay = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)

    try:
        font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 32)
    except Exception:
        font = ImageFont.load_default()

    words = subtitle_text.split()
    lines, current = [], []
    for word in words:
        current.append(word)
        if len(" ".join(current)) > 20:
            lines.append(" ".join(current[:-1]))
            current = [word]
    if current:
        lines.append(" ".join(current))

    y = int(h * 0.70)
    for line in lines:
        bbox = draw.textbbox((0, 0), line, font=font)
        tw = bbox[2] - bbox[0]
        th = bbox[3] - bbox[1]
        x = (w - tw) // 2

        pad = 8
        draw.rectangle([x - pad, y - pad, x + tw + pad, y + th + pad], fill=(0, 0, 0, 210))
        draw.text((x, y), line, fill=(255, 230, 0, 255), font=font)
        y += th + 14

    final_img = Image.alpha_composite(base, overlay).convert("RGB")
    final_img.save(img_path, quality=85)
    base.close()
    overlay.close()

async def build_viral_reel(topic):
    prompt = f"""
    Topic: '{topic}'
    Give 3 scenes structure in JSON for YouTube Shorts/Reels.
    Output ONLY valid JSON:
    {{
      "full_script": "20 second ki Hindi voiceover script bina kisi bracket ke",
      "scenes": [
        {{"text": "Scene 1 Hindi Subtitle", "image_prompt": "cinematic hyperrealistic subject in english"}},
        {{"text": "Scene 2 Hindi Subtitle", "image_prompt": "cinematic hyperrealistic subject in english"}},
        {{"text": "Scene 3 Hindi Subtitle", "image_prompt": "cinematic hyperrealistic subject in english"}}
      ]
    }}
    """
    res = model.generate_content(prompt)
    raw = res.text.replace("```json", "").replace("```", "").strip()
    data = json.loads(raw)

    full_script = data["full_script"]
    scenes = data["scenes"]

    audio_path = "voiceover.mp3"
    comm = edge_tts.Communicate(full_script, voice="hi-IN-MadhurNeural")
    await comm.save(audio_path)

    audio_clip = AudioFileClip(audio_path)
    total_dur = audio_clip.duration
    scene_dur = max(3.0, total_dur / len(scenes))

    video_clips = []
    temp_files = [audio_path]

    for idx, sc in enumerate(scenes):
        img_name = f"scene_{idx}.jpg"
        temp_files.append(img_name)
        ok = download_ai_image(sc["image_prompt"], img_name)
        
        if not ok or not os.path.exists(img_name):
            img = Image.new("RGB", (540, 960), color=(20, 20, 30))
            img.save(img_name)

        add_subtitles_to_image(img_name, sc["text"])
        
        try:
            ic = ImageClip(img_name, duration=scene_dur)
        except Exception:
            ic = ImageClip(img_name)
            ic.duration = scene_dur

        video_clips.append(ic)

    final_out = "viral_reel_out.mp4"
    temp_files.append(final_out)

    final_video = concatenate_videoclips(video_clips, method="compose")
    if hasattr(final_video, "with_audio"):
        final_with_audio = final_video.with_audio(audio_clip)
    else:
        final_with_audio = final_video.set_audio(audio_clip)

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
    final_video.close()
    final_with_audio.close()
    for c in video_clips:
        c.close()

    gc.collect()
    return full_script, audio_path, final_out, temp_files

async def generate_reel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    topic = " ".join(context.args)
    if not topic:
        await update.message.reply_text("कृपया विषय लिखें। उदाहरण: `/reel समय यात्रा का सच`")
        return

    wait_msg = await update.message.reply_text("🎨 AI दृश्य और सबटाइटल तैयार हो रहे हैं...")
    temp_files = []
    try:
        script, audio, video, temp_files = await build_viral_reel(topic)
        await update.message.reply_text(f"📝 *स्क्रिप्ट:*\n\n{script}", parse_mode="Markdown")

        if os.path.exists(video):
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
    await update.message.reply_text("👑 Hermes AI Studio सक्रिय है!\n\nकमांड भेजें:\n`/reel <विषय>`")

if __name__ == "__main__":
    threading.Thread(target=run_http_server, daemon=True).start()
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("reel", generate_reel))
    app.run_polling()
