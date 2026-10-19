import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.environ.get("DATA_DIR", os.path.join(BASE_DIR, "data"))
JOBS_DIR = os.path.join(DATA_DIR, "jobs")
FONT_PATH = os.path.join(BASE_DIR, "fonts", "DejaVuSans-Bold.ttf")

# DEMO=1: LLM, images and voice are replaced by local stubs (for offline testing)
DEMO = os.environ.get("DEMO", "") == "1"

APP_PASSWORD = os.environ.get("APP_PASSWORD", "")
PUBLIC_URL = os.environ.get("PUBLIC_URL", "").rstrip("/")  # e.g. https://autotube.onrender.com
ON_RENDER = bool(os.environ.get("RENDER"))

GOOGLE_CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID", "")
GOOGLE_CLIENT_SECRET = os.environ.get("GOOGLE_CLIENT_SECRET", "")

os.makedirs(JOBS_DIR, exist_ok=True)

VOICES = {
    "kk": [("kk-KZ-DauletNeural", "Дәулет (ер)"), ("kk-KZ-AigulNeural", "Айгүл (әйел)")],
    "ru": [("ru-RU-DmitryNeural", "Дмитрий (ер)"), ("ru-RU-SvetlanaNeural", "Светлана (әйел)")],
    "en": [("en-US-GuyNeural", "Guy (male)"), ("en-US-JennyNeural", "Jenny (female)")],
}
LANG_NAMES = {"kk": "Kazakh", "ru": "Russian", "en": "English"}

STYLES = {
    "cinematic": "cinematic film still, dramatic lighting, ultra detailed, 35mm photo",
    "cartoon": "vibrant 3D cartoon illustration, soft light, clean shapes, pixar-like",
    "realistic": "photorealistic, natural light, high detail, sharp focus",
    "dark": "dark moody neon atmosphere, high contrast, cyber techno look",
    "flat": "flat vector illustration, minimal, bold colors, clean background",
}
STYLE_SUFFIX = ", no text, no letters, no watermark"

# video formats: (width, height, scenes, target words, caption words per chunk)
FORMATS = {
    "short": dict(w=720, h=1280, scenes=7, words=110, chunk=6),
    "long": dict(w=1280, h=720, scenes=16, words=750, chunk=11),
}
