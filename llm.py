"""Script writer. Uses free LLM endpoints (OpenAI-compatible).

Order: Gemini free key -> Groq free key -> Pollinations (no key needed).
"""
import json
import os
import re
import time

import requests

import config


def providers():
    """(name, url, model, key). Keyed free tiers first, keyless Pollinations models last."""
    p = []
    if os.environ.get("GEMINI_API_KEY"):
        p.append((
            "gemini",
            "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions",
            os.environ.get("GEMINI_MODEL", "gemini-flash-latest"),
            os.environ["GEMINI_API_KEY"],
        ))
    if os.environ.get("GROQ_API_KEY"):
        p.append((
            "groq",
            "https://api.groq.com/openai/v1/chat/completions",
            os.environ.get("GROQ_MODEL", "llama-3.3-70b-versatile"),
            os.environ["GROQ_API_KEY"],
        ))
    for m in ("openai", "mistral", "llama"):
        p.append((f"pollinations/{m}", "https://text.pollinations.ai/openai", m, None))
    return p


def provider_name():
    return "demo" if config.DEMO else providers()[0][0].split("/")[0]


def _content(resp_json):
    """Pull the text out of an OpenAI-style reply, tolerating odd shapes."""
    choice = (resp_json.get("choices") or [{}])[0]
    msg = choice.get("message") or {}
    text = msg.get("content") or msg.get("reasoning_content") or choice.get("text") or ""
    if isinstance(text, list):  # content parts
        text = "".join(part.get("text", "") for part in text if isinstance(part, dict))
    return text


def chat(messages, temperature=0.8):
    errors = []
    for name, url, model, key in providers():
        for attempt in range(2):
            try:
                headers = {"Content-Type": "application/json"}
                if key:
                    headers["Authorization"] = f"Bearer {key}"
                r = requests.post(
                    url,
                    headers=headers,
                    json={"model": model, "messages": messages, "temperature": temperature},
                    timeout=120,
                )
                if r.status_code != 200:
                    errors.append(f"{name}: HTTP {r.status_code} {r.text[:120]}")
                    time.sleep(2)
                    continue
                try:
                    text = _content(r.json())
                except ValueError:
                    text = r.text  # some endpoints answer with plain text
                if text and text.strip() and "SCENE" in text.upper():
                    return text
                errors.append(f"{name}: жауап бос немесе форматы басқа ({r.text[:120]!r})")
            except Exception as e:  # noqa: BLE001
                errors.append(f"{name}: {e}")
            time.sleep(2)
    raise RuntimeError("LLM қолжетімсіз: " + " | ".join(errors[-3:]))


def _extract_json(text):
    text = text.strip()
    text = re.sub(r"^```(?:json)?|```$", "", text, flags=re.M).strip()
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("JSON табылмады")
    return json.loads(text[start:end + 1])


def _demo_package(topic, kind, lang, n):
    scenes = [
        {
            "narration": f"{topic}. Бөлім {i + 1}. Бұл тест үшін жасалған қысқа мәтін.",
            "image_prompt": f"abstract scene {i + 1} about {topic}",
        }
        for i in range(n)
    ]
    return {"title": topic[:90], "description": f"{topic} туралы тест видео.", "tags": ["test", "demo"], "scenes": scenes}


def make_package(topic, script, kind, lang, style_key):
    fmt = config.FORMATS[kind]
    if config.DEMO:
        n = 2
        return _demo_package(topic, kind, lang, n)

    lang_name = config.LANG_NAMES[lang]
    system = "You are a YouTube scriptwriter. Follow the requested plain-text format exactly. No markdown, no code fences."
    if script and script.strip():
        source = (
            "Use the narration below VERBATIM (you may only split it into scenes). "
            f"Narration:\n\"\"\"\n{script.strip()}\n\"\"\""
        )
    else:
        source = (
            f"Write the narration yourself. Total about {fmt['words']} words, "
            f"split into about {fmt['scenes']} scenes. "
            "Scene 1 is a strong hook in the first sentence. The last scene is a short call to subscribe. "
            "Be factual: do not invent statistics, quotes or claims; no medical, legal or financial promises."
        )
    user = f"""Topic: {topic}
Video type: {"vertical YouTube Short (under 60 seconds)" if kind == "short" else "long horizontal YouTube video (about 5 minutes)"}
Narration, title and description language: {lang_name}.
{source}

Reply in EXACTLY this plain-text format (keep the English keywords as written):

TITLE: catchy title, max 90 characters
DESCRIPTION: 2-4 sentences ending with 3 hashtags
TAGS: 8-12 short tags separated by commas

SCENE
NARRATION: text spoken in this scene, in {lang_name}, plain sentences, no emojis, no markdown
IMAGE: ENGLISH description of the picture for this scene, concrete subject and setting, no text in the image

SCENE
NARRATION: ...
IMAGE: ...

(repeat SCENE blocks for every scene)"""
    last_err = None
    for _ in range(3):
        try:
            raw = chat([{"role": "system", "content": system}, {"role": "user", "content": user}])
            return _parse_package(raw, topic)
        except Exception as e:  # noqa: BLE001
            last_err = e
    raise RuntimeError(f"Сценарий жасалмады: {last_err}")


def _field(block, key):
    m = re.search(rf"^\s*\**{key}\**\s*:\s*(.+?)(?=^\s*\**(?:TITLE|DESCRIPTION|TAGS|NARRATION|IMAGE|SCENE)\**\s*:?\s*$|^\s*\**(?:TITLE|DESCRIPTION|TAGS|NARRATION|IMAGE)\**\s*:|\Z)",
                  block, flags=re.S | re.M | re.I)
    return re.sub(r"\s+", " ", m.group(1)).strip().strip("*").strip() if m else ""


def _parse_package(raw, topic):
    raw = re.sub(r"```\w*", "", raw).replace("\r", "")
    parts = re.split(r"^\s*\**SCENE\b[^\n]*$", raw, flags=re.M | re.I)
    head, blocks = parts[0], parts[1:]
    scenes = []
    for b in blocks:
        narr = _field(b, "NARRATION")
        if narr:
            scenes.append({"narration": narr, "image_prompt": _field(b, "IMAGE") or topic})
    if not scenes:
        raise ValueError("сахналар табылмады")
    tags = [t.strip().lstrip("#")[:30] for t in re.split(r"[,;]", _field(head, "TAGS")) if t.strip()][:15]
    return {
        "title": (_field(head, "TITLE") or topic)[:95],
        "description": _field(head, "DESCRIPTION"),
        "tags": tags,
        "scenes": scenes,
    }
