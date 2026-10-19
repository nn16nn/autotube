import os
import shutil
import traceback

import config
import db
import llm
import media
import youtube


def _stage(job_id, stage, progress):
    db.update_job(job_id, stage=stage, progress=progress)


def build_video(job):
    """script -> images -> voice -> clips -> final.mp4. Returns paths and metadata."""
    jid = job["id"]
    kind = job["kind"]
    fmt = config.FORMATS[kind]
    w, h = fmt["w"], fmt["h"]
    jobdir = os.path.join(config.JOBS_DIR, str(jid))
    work = os.path.join(jobdir, "work")
    shutil.rmtree(work, ignore_errors=True)
    os.makedirs(work, exist_ok=True)

    _stage(jid, "Сценарий жазылып жатыр", 5)
    pkg = llm.make_package(job["topic"], job.get("script"), kind, job["lang"], job["style"])
    scenes = pkg["scenes"]
    n = len(scenes)
    db.update_job(jid, title=pkg["title"], description=pkg["description"], tags=pkg["tags"])

    clips = []
    first_bg = None
    seed_base = 1000 + jid * 37
    for i, sc in enumerate(scenes):
        base = 8 + int(80 * i / n)
        _stage(jid, f"Сахна {i + 1}/{n}: сурет", base)
        bg = os.path.join(work, f"bg_{i}.jpg")
        media.fetch_image(sc["image_prompt"], job["style"], w, h, seed_base + i, bg)
        first_bg = first_bg or bg

        _stage(jid, f"Сахна {i + 1}/{n}: дауыс", base + int(40 / n))
        audio = os.path.join(work, f"voice_{i}.{'wav' if config.DEMO else 'mp3'}")
        media.tts(sc["narration"], job["voice"], audio)

        _stage(jid, f"Сахна {i + 1}/{n}: монтаж", base + int(70 / n))
        chunks = media.split_chunks(sc["narration"], fmt["chunk"])
        clip = os.path.join(work, f"clip_{i}.mp4")
        media.make_clip(bg, audio, chunks, w, h, kind, i, work, clip)
        clips.append(clip)

    _stage(jid, "Видео жиналып жатыр", 92)
    final = os.path.join(jobdir, "final.mp4")
    media.concat(clips, work, final)
    thumb = os.path.join(jobdir, "thumb.jpg")
    media.thumbnail(first_bg, pkg["title"], thumb)
    shutil.rmtree(work, ignore_errors=True)
    db.update_job(jid, video_path=final, thumb_path=thumb)
    return pkg


def upload_job(job_id):
    job = db.get_job(job_id)
    if not youtube.connected():
        raise RuntimeError("YouTube қосылмаған")
    _stage(job_id, "YouTube-қа жүктелуде", 95)
    desc = job["description"] or ""
    if job["kind"] == "short" and "#shorts" not in desc.lower():
        desc += "\n#Shorts"
    vid = youtube.upload(
        job["video_path"], job["thumb_path"], job["title"], desc, job["tags"],
        job["privacy"], job["publish_at"],
    )
    db.update_job(job_id, youtube_id=vid, status="uploaded", stage="YouTube-қа жүктелді", progress=100, error=None)
    return vid


def run_job(job_id):
    job = db.get_job(job_id)
    if not job:
        return
    db.update_job(job_id, status="running", error=None, progress=1, stage="Басталды")
    try:
        build_video(job)
        db.update_job(job_id, status="ready", stage="Дайын", progress=100)
        if job["auto_upload"]:
            try:
                upload_job(job_id)
            except Exception as e:  # noqa: BLE001  # keep the finished video even if upload fails
                db.update_job(job_id, status="ready", stage="Дайын (жүктеу сәтсіз)", progress=100,
                              error=f"Жүктеу қатесі: {e}")
    except Exception as e:  # noqa: BLE001
        traceback.print_exc()
        db.update_job(job_id, status="error", stage="Қате", error=str(e)[:800])
