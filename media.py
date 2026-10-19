"""Images, voice, captions and ffmpeg rendering."""
import asyncio
import colorsys
import os
import random
import re
import subprocess
import time
from urllib.parse import quote

import imageio_ffmpeg
import requests
from PIL import Image, ImageDraw, ImageFont

import config

FFMPEG = imageio_ffmpeg.get_ffmpeg_exe()
FPS = 25


def run_ffmpeg(args):
    p = subprocess.run([FFMPEG, "-y", "-hide_banner", "-loglevel", "error"] + args,
                       capture_output=True, text=True)
    if p.returncode != 0:
        raise RuntimeError("ffmpeg қатесі: " + p.stderr[-600:])


def audio_duration(path):
    p = subprocess.run([FFMPEG, "-hide_banner", "-i", path], capture_output=True, text=True)
    m = re.search(r"Duration:\s*(\d+):(\d+):(\d+\.?\d*)", p.stderr)
    if not m:
        raise RuntimeError("Аудио ұзақтығы анықталмады")
    h, mi, s = m.groups()
    return int(h) * 3600 + int(mi) * 60 + float(s)


# ---------- images ----------

def gradient_image(w, h, seed, out, label=""):
    rnd = random.Random(seed)
    hue = rnd.random()
    c1 = tuple(int(x * 255) for x in colorsys.hsv_to_rgb(hue, 0.65, 0.55))
    c2 = tuple(int(x * 255) for x in colorsys.hsv_to_rgb((hue + 0.12) % 1, 0.75, 0.18))
    img = Image.new("RGB", (w, h))
    d = ImageDraw.Draw(img)
    for y in range(h):
        t = y / h
        d.line([(0, y), (w, y)], fill=tuple(int(c1[i] * (1 - t) + c2[i] * t) for i in range(3)))
    img.save(out, quality=92)


def fetch_image(prompt, style_key, w, h, seed, out):
    """Pollinations (free, no key). Falls back to a gradient so the video is never blocked."""
    if config.DEMO:
        gradient_image(w, h, seed, out)
        return "demo"
    full = f"{prompt}, {config.STYLES.get(style_key, config.STYLES['cinematic'])}{config.STYLE_SUFFIX}"
    url = (f"https://image.pollinations.ai/prompt/{quote(full)}"
           f"?width={w}&height={h}&seed={seed}&nologo=true&model=flux")
    for attempt in range(4):
        try:
            r = requests.get(url, timeout=120)
            if r.status_code == 200 and r.headers.get("content-type", "").startswith("image") and len(r.content) > 5000:
                with open(out, "wb") as f:
                    f.write(r.content)
                Image.open(out).convert("RGB").save(out, quality=92)
                return "ok"
        except Exception:  # noqa: BLE001
            pass
        time.sleep(4 * (attempt + 1))
    gradient_image(w, h, seed, out)
    return "fallback"


# ---------- voice ----------

def tts(text, voice, out):
    if config.DEMO:
        words = max(1, len(text.split()))
        run_ffmpeg(["-f", "lavfi", "-i", "anullsrc=r=24000:cl=mono", "-t", str(words * 0.45),
                    "-c:a", "pcm_s16le", out])
        return
    import edge_tts

    async def _go():
        await edge_tts.Communicate(text, voice).save(out)

    last = None
    for attempt in range(4):
        try:
            asyncio.run(_go())
            if os.path.exists(out) and os.path.getsize(out) > 500:
                return
        except Exception as e:  # noqa: BLE001
            last = e
        time.sleep(3 * (attempt + 1))
    raise RuntimeError(f"Дауыс жасалмады (edge-tts): {last}")


# ---------- captions ----------

def split_chunks(text, max_words):
    sentences = re.split(r"(?<=[.!?…])\s+", text.strip())
    chunks = []
    for s in sentences:
        words = s.split()
        if not words:
            continue
        n = max(1, -(-len(words) // max_words))  # even split of long sentences
        size = -(-len(words) // n)
        for i in range(0, len(words), size):
            chunks.append(" ".join(words[i:i + size]))
    return chunks or [text]


def _wrap(draw, text, font, max_w):
    lines, cur = [], ""
    for word in text.split():
        t = (cur + " " + word).strip()
        if draw.textlength(t, font=font) <= max_w:
            cur = t
        else:
            if cur:
                lines.append(cur)
            cur = word
    if cur:
        lines.append(cur)
    return lines


def caption_png(text, w, h, kind, out):
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    size = w // 15 if kind == "short" else h // 17
    max_w = int(w * 0.86)
    while True:
        font = ImageFont.truetype(config.FONT_PATH, size)
        lines = _wrap(d, text, font, max_w)
        if len(lines) <= 4 or size < 22:
            break
        size -= 3
    lh = int(size * 1.25)
    block_h = lh * len(lines)
    bottom = int(h * (0.80 if kind == "short" else 0.92))
    top = bottom - block_h
    pad = int(size * 0.45)
    box_w = max(d.textlength(l, font=font) for l in lines) + pad * 2
    x0 = (w - box_w) / 2
    d.rounded_rectangle([x0, top - pad, x0 + box_w, bottom + pad], radius=pad, fill=(0, 0, 0, 120))
    y = top
    for l in lines:
        tw = d.textlength(l, font=font)
        d.text(((w - tw) / 2, y), l, font=font, fill="white", stroke_width=max(2, size // 14), stroke_fill="black")
        y += lh
    img.save(out)


# ---------- video ----------

def make_clip(bg, audio, chunks, w, h, kind, idx, workdir, out):
    dur = audio_duration(audio) + 0.35
    frames = int(dur * FPS) + 2
    total_chars = sum(len(c) for c in chunks) or 1
    t, timeline = 0.0, []
    for i, c in enumerate(chunks):
        d = (dur - 0.35) * len(c) / total_chars
        end = dur if i == len(chunks) - 1 else t + d
        p = os.path.join(workdir, f"cap_{idx}_{i}.png")
        caption_png(c, w, h, kind, p)
        timeline.append((p, t, end))
        t = end

    inc = 0.12 / frames
    if idx % 2 == 0:
        z = f"min(zoom+{inc:.6f},1.12)"
    else:
        z = f"if(eq(on,0),1.12,max(zoom-{inc:.6f},1.0))"
    args = ["-i", bg]
    for p, _, _ in timeline:
        args += ["-loop", "1", "-framerate", str(FPS), "-t", f"{dur:.2f}", "-i", p]
    args += ["-i", audio]
    fc = (f"[0:v]scale={w * 2}:{h * 2}:force_original_aspect_ratio=increase,crop={w * 2}:{h * 2},"
          f"zoompan=z='{z}':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d={frames}:s={w}x{h}:fps={FPS}[v0]")
    for i, (_, a, b) in enumerate(timeline):
        fc += f";[v{i}][{i + 1}:v]overlay=0:0:enable='between(t,{a:.2f},{b:.2f})'[v{i + 1}]"
    fc += f";[{len(timeline) + 1}:a]apad=pad_dur=0.4,aresample=44100,aformat=channel_layouts=stereo[a]"
    run_ffmpeg(args + ["-filter_complex", fc, "-map", f"[v{len(timeline)}]", "-map", "[a]",
                       "-t", f"{dur:.2f}", "-c:v", "libx264", "-preset", "veryfast", "-crf", "24",
                       "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "128k", "-r", str(FPS), out])
    return dur


def concat(clips, workdir, out):
    lst = os.path.join(workdir, "list.txt")
    with open(lst, "w") as f:
        for c in clips:
            f.write(f"file '{c}'\n")
    run_ffmpeg(["-f", "concat", "-safe", "0", "-i", lst, "-c", "copy", "-movflags", "+faststart", out])


def thumbnail(bg, title, out):
    W, H = 1280, 720
    img = Image.open(bg).convert("RGB")
    ratio = max(W / img.width, H / img.height)
    img = img.resize((int(img.width * ratio), int(img.height * ratio)))
    left, top = (img.width - W) // 2, (img.height - H) // 2
    img = img.crop((left, top, left + W, top + H))
    ov = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    od = ImageDraw.Draw(ov)
    for y in range(H // 2, H):
        od.line([(0, y), (W, y)], fill=(0, 0, 0, int(190 * (y - H // 2) / (H // 2))))
    img = Image.alpha_composite(img.convert("RGBA"), ov)
    d = ImageDraw.Draw(img)
    size = 84
    while True:
        font = ImageFont.truetype(config.FONT_PATH, size)
        lines = _wrap(d, title, font, W - 120)
        if len(lines) <= 3 or size < 40:
            break
        size -= 6
    y = H - 50 - int(size * 1.2) * len(lines)
    for l in lines:
        d.text((60, y), l, font=font, fill="white", stroke_width=5, stroke_fill="black")
        y += int(size * 1.2)
    img.convert("RGB").save(out, quality=90)
