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
    p.append(("pollinations", "https://text.pollinations.ai/openai", "openai", None))
    return p


def provider_name():
    return "demo" if config.DEMO else providers()[0][0]


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
                r.raise_for_status()
                text = r.json()["choices"][0]["message"]["content"]
                if text and text.strip():
                    return text
                errors.append(f"{name}: empty reply")
            except Exception as e:  # noqa: BLE001
                errors.append(f"{name}: {e}")
                time.sleep(3)
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
    system = (
        "You are a YouTube scriptwriter. Reply with ONE valid JSON object and nothing else."
    )
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
Narration language: {lang_name}. Title and description language: {lang_name}.
{source}

JSON schema:
{{
  "title": "catchy title, max 90 characters",
  "description": "2-4 sentences + 3 hashtags",
  "tags": ["8-12 short tags"],
  "scenes": [
    {{"narration": "text spoken in this scene, in {lang_name}, plain sentences without emojis or markdown",
      "image_prompt": "ENGLISH visual description of the picture for this scene, concrete subject and setting, no text in the image"}}
  ]
}}"""
    last_err = None
    for _ in range(3):
        try:
            raw = chat([{"role": "system", "content": system}, {"role": "user", "content": user}])
            data = _extract_json(raw)
            scenes = [
                {"narration": str(s["narration"]).strip(), "image_prompt": str(s.get("image_prompt") or topic).strip()}
                for s in data["scenes"]
                if str(s.get("narration", "")).strip()
            ]
            if not scenes:
                raise ValueError("сахналар бос")
            return {
                "title": str(data.get("title") or topic)[:95],
                "description": str(data.get("description") or ""),
                "tags": [str(t).lstrip("#")[:30] for t in (data.get("tags") or [])][:15],
                "scenes": scenes,
            }
        except Exception as e:  # noqa: BLE001
            last_err = e
    raise RuntimeError(f"Сценарий жасалмады: {last_err}")
