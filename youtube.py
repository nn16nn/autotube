"""YouTube OAuth + upload (Data API v3)."""
import json
import os

import config
import db

SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]
TOKEN_KEY = "youtube_token"


def configured():
    return bool(config.GOOGLE_CLIENT_ID and config.GOOGLE_CLIENT_SECRET)


def _redirect_uri():
    return f"{config.PUBLIC_URL}/youtube/callback"


def _flow():
    from google_auth_oauthlib.flow import Flow

    cfg = {"web": {
        "client_id": config.GOOGLE_CLIENT_ID,
        "client_secret": config.GOOGLE_CLIENT_SECRET,
        "auth_uri": "https://accounts.google.com/o/oauth2/auth",
        "token_uri": "https://oauth2.googleapis.com/token",
        "redirect_uris": [_redirect_uri()],
    }}
    flow = Flow.from_client_config(cfg, scopes=SCOPES, autogenerate_code_verifier=False)
    flow.redirect_uri = _redirect_uri()
    return flow


def auth_url():
    url, state = _flow().authorization_url(access_type="offline", prompt="consent",
                                           include_granted_scopes="true")
    return url, state


def finish_auth(code):
    flow = _flow()
    flow.fetch_token(code=code)
    db.set_setting(TOKEN_KEY, flow.credentials.to_json())


def disconnect():
    db.set_setting(TOKEN_KEY, None)


def _token_json():
    return os.environ.get("YT_TOKEN_JSON") or db.get_setting(TOKEN_KEY)


def connected():
    return bool(_token_json())


def _credentials():
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials

    creds = Credentials.from_authorized_user_info(json.loads(_token_json()), SCOPES)
    if not creds.valid:
        creds.refresh(Request())
        if not os.environ.get("YT_TOKEN_JSON"):
            db.set_setting(TOKEN_KEY, creds.to_json())
    return creds


def upload(video_path, thumb_path, title, description, tags, privacy, publish_at):
    """publish_at: RFC3339 UTC string -> video is uploaded private and YouTube publishes it at that time."""
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaFileUpload

    yt = build("youtube", "v3", credentials=_credentials(), cache_discovery=False)
    status = {
        "privacyStatus": "private" if publish_at else privacy,
        "selfDeclaredMadeForKids": False,
        "containsSyntheticMedia": True,  # AI-generated visuals/voice: disclose honestly
    }
    if publish_at:
        status["publishAt"] = publish_at
    body = {
        "snippet": {"title": title[:100], "description": description[:4900], "tags": tags, "categoryId": "22"},
        "status": status,
    }
    media = MediaFileUpload(video_path, mimetype="video/mp4", chunksize=8 * 1024 * 1024, resumable=True)
    req = yt.videos().insert(part="snippet,status", body=body, media_body=media)
    resp = None
    while resp is None:
        _, resp = req.next_chunk()
    vid = resp["id"]
    try:
        yt.thumbnails().set(videoId=vid, media_body=MediaFileUpload(thumb_path, mimetype="image/jpeg")).execute()
    except Exception:  # noqa: BLE001  # thumbnails need a verified channel; not fatal
        pass
    return vid
