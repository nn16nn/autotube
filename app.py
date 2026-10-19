import datetime as dt
import hmac
import os
import secrets
import shutil
import threading
import time

from flask import (Flask, abort, jsonify, redirect, render_template, request,
                   send_file, session)
from werkzeug.middleware.proxy_fix import ProxyFix

import config
import db
import llm
import pipeline
import youtube

db.init()

app = Flask(__name__)
app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1, x_host=1)

_key_file = os.path.join(config.DATA_DIR, ".secret_key")
if os.environ.get("SECRET_KEY"):
    app.secret_key = os.environ["SECRET_KEY"]
else:
    if not os.path.exists(_key_file):
        with open(_key_file, "w") as f:
            f.write(secrets.token_hex(32))
    app.secret_key = open(_key_file).read()
app.config.update(SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE="Lax",
                  SESSION_COOKIE_SECURE=config.ON_RENDER, MAX_CONTENT_LENGTH=1024 * 1024)

if config.PUBLIC_URL == "":
    config.PUBLIC_URL = ""  # filled from request on first use


# ---------------- worker ----------------
_worker_started = False
_worker_lock = threading.Lock()


def _worker():
    while True:
        try:
            job = db.next_due_job()
            if job:
                pipeline.run_job(job["id"])
                continue
        except Exception:  # noqa: BLE001
            import traceback
            traceback.print_exc()
        time.sleep(5)


def start_worker():
    global _worker_started
    with _worker_lock:
        if not _worker_started:
            threading.Thread(target=_worker, daemon=True, name="worker").start()
            _worker_started = True


start_worker()


# ---------------- auth ----------------
def _authed():
    if not config.APP_PASSWORD:
        return not config.ON_RENDER  # open only for local use
    return session.get("ok") is True


@app.before_request
def guard():
    if request.path in ("/login", "/health") or request.path.startswith("/static"):
        return None
    if config.ON_RENDER and not config.APP_PASSWORD:
        return ("APP_PASSWORD орнатылмаған. Render → Environment бөлімінде APP_PASSWORD қосыңыз.", 503)
    if not _authed():
        if request.path.startswith("/api") or request.path.startswith("/media"):
            return jsonify(error="auth"), 401
        return redirect("/login")
    if request.method == "POST":  # basic CSRF guard: same-origin only
        origin = request.headers.get("Origin")
        if origin and request.host not in origin:
            abort(403)
    return None


@app.route("/login", methods=["GET", "POST"])
def login():
    err = ""
    if request.method == "POST":
        if config.APP_PASSWORD and hmac.compare_digest(request.form.get("password", ""), config.APP_PASSWORD):
            session["ok"] = True
            return redirect("/")
        err = "Құпиясөз қате"
        time.sleep(1)
    return render_template("login.html", err=err)


@app.route("/logout")
def logout():
    session.clear()
    return redirect("/login")


@app.route("/health")
def health():
    return "ok"


# ---------------- pages / api ----------------
@app.route("/")
def index():
    return render_template("index.html", voices=config.VOICES, styles=list(config.STYLES))


def _public_url():
    return config.PUBLIC_URL or request.host_url.rstrip("/")


@app.route("/api/status")
def status():
    return jsonify(
        youtube=youtube.connected(),
        youtube_configured=youtube.configured(),
        llm=llm.provider_name(),
        demo=config.DEMO,
        redirect_uri=_public_url() + "/youtube/callback",
    )


def _view(j):
    return {
        "id": j["id"], "topic": j["topic"], "kind": j["kind"], "status": j["status"],
        "stage": j["stage"], "progress": j["progress"], "title": j["title"],
        "description": j["description"], "tags": j["tags"], "error": j["error"],
        "youtube_id": j["youtube_id"], "publish_at": j["publish_at"], "privacy": j["privacy"],
        "has_video": bool(j["video_path"] and os.path.exists(j["video_path"])),
        "auto_upload": bool(j["auto_upload"]),
    }


@app.route("/api/jobs", methods=["GET"])
def jobs_list():
    return jsonify([_view(j) for j in db.list_jobs()])


@app.route("/api/jobs", methods=["POST"])
def jobs_create():
    d = request.get_json(force=True, silent=True) or {}
    topics = [t.strip() for t in (d.get("topics") or "").splitlines() if t.strip()][:30]
    if not topics:
        return jsonify(error="Тақырып бос"), 400
    kinds = ["short", "long"] if d.get("kind") == "both" else [d.get("kind", "short")]
    lang = d.get("lang", "kk")
    if lang not in config.VOICES:
        return jsonify(error="Тіл қате"), 400
    voice = d.get("voice") or config.VOICES[lang][0][0]
    if voice not in [v for v, _ in config.VOICES[lang]]:
        voice = config.VOICES[lang][0][0]
    style = d.get("style") if d.get("style") in config.STYLES else "cinematic"
    privacy = d.get("privacy") if d.get("privacy") in ("private", "unlisted", "public") else "private"
    script = (d.get("script") or "").strip() if len(topics) == 1 else ""

    start = None
    if d.get("start_at"):
        start = dt.datetime.fromisoformat(d["start_at"].replace("Z", "+00:00"))
    gap = float(d.get("interval_hours") or 24)
    ids = []
    slot = 0
    for t in topics:
        for k in kinds:
            if k not in config.FORMATS:
                continue
            pub = None
            if start:
                pub = (start + dt.timedelta(hours=gap * slot)).astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
                slot += 1
            ids.append(db.create_job(
                topic=t[:200], script=script, kind=k, lang=lang, voice=voice, style=style,
                auto_upload=1 if d.get("auto_upload") else 0, privacy=privacy,
                publish_at=pub, run_at=None,
            ))
    return jsonify(ids=ids)


@app.route("/api/jobs/<int:jid>/retry", methods=["POST"])
def job_retry(jid):
    j = db.get_job(jid) or abort(404)
    if j["status"] == "running":
        return jsonify(error="Жұмыс істеп тұр"), 409
    db.update_job(jid, status="queued", error=None, progress=0, stage="Кезекте")
    return jsonify(ok=True)


@app.route("/api/jobs/<int:jid>/upload", methods=["POST"])
def job_upload(jid):
    j = db.get_job(jid) or abort(404)
    if not j["video_path"] or not os.path.exists(j["video_path"]):
        return jsonify(error="Видео жоқ"), 400
    if j["status"] == "running":
        return jsonify(error="Жұмыс істеп тұр"), 409

    def go():
        db.update_job(jid, status="running", error=None)
        try:
            pipeline.upload_job(jid)
        except Exception as e:  # noqa: BLE001
            db.update_job(jid, status="ready", stage="Дайын (жүктеу сәтсіз)", progress=100, error=f"Жүктеу қатесі: {e}")

    threading.Thread(target=go, daemon=True).start()
    return jsonify(ok=True)


@app.route("/api/jobs/<int:jid>", methods=["DELETE"])
def job_delete(jid):
    j = db.get_job(jid) or abort(404)
    if j["status"] == "running":
        return jsonify(error="Жұмыс істеп тұр"), 409
    shutil.rmtree(os.path.join(config.JOBS_DIR, str(jid)), ignore_errors=True)
    db.delete_job(jid)
    return jsonify(ok=True)


@app.route("/media/<int:jid>/<what>")
def media_file(jid, what):
    j = db.get_job(jid) or abort(404)
    if what == "video" and j["video_path"] and os.path.exists(j["video_path"]):
        return send_file(j["video_path"], mimetype="video/mp4", conditional=True,
                         as_attachment=request.args.get("dl") == "1",
                         download_name=f"video_{jid}.mp4")
    if what == "thumb" and j["thumb_path"] and os.path.exists(j["thumb_path"]):
        return send_file(j["thumb_path"], mimetype="image/jpeg", conditional=True)
    abort(404)


# ---------------- youtube oauth ----------------
@app.route("/youtube/connect")
def yt_connect():
    if not youtube.configured():
        return "GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET орнатылмаған", 400
    config.PUBLIC_URL = config.PUBLIC_URL or _public_url()
    url, state = youtube.auth_url()
    session["yt_state"] = state
    return redirect(url)


@app.route("/youtube/callback")
def yt_callback():
    if request.args.get("state") != session.get("yt_state") or not request.args.get("code"):
        return "OAuth қатесі: " + request.args.get("error", "state сәйкес емес"), 400
    config.PUBLIC_URL = config.PUBLIC_URL or _public_url()
    youtube.finish_auth(request.args["code"])
    return redirect("/")


@app.route("/youtube/disconnect", methods=["POST"])
def yt_disconnect():
    youtube.disconnect()
    return jsonify(ok=True)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)), debug=False)
