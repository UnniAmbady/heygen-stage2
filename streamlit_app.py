# Hey Gen-Stage.2-Ver.5
# from openai import OpenAI
import json
import time
from pathlib import Path

import requests
import streamlit as st
import streamlit.components.v1 as components

# ---------- Page ----------
st.set_page_config(page_title="AI Avatar Demo", layout="centered")
st.title("AI Avatar Demo")

# ---------- Secrets ----------
OPENAI_API_KEY = st.secrets["openai"]["secret_key"]
HEYGEN_API_KEY = st.secrets["HeyGen"]["heygen_api_key"]

# ---------- Endpoints ----------
BASE = "https://api.heygen.com/v1"
API_LIST_AVATARS = f"{BASE}/streaming/avatar.list"    # GET  (x-api-key)
API_STREAM_NEW   = f"{BASE}/streaming.new"            # POST (x-api-key) -> offer.sdp
API_CREATE_TOKEN = f"{BASE}/streaming.create_token"   # POST (x-api-key) -> session token
API_STREAM_TASK  = f"{BASE}/streaming.task"           # POST (Bearer)
API_STREAM_STOP  = f"{BASE}/streaming.stop"           # POST (Bearer)

# ---------- Headers ----------
HEADERS_XAPI = {
    "accept": "application/json",
    "x-api-key": HEYGEN_API_KEY,
    "Content-Type": "application/json",
}
def headers_bearer(token: str):
    return {
        "accept": "application/json",
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }

# ---------- HTTP helpers (surface server body on error) ----------
def _get(url, params=None):
    r = requests.get(url, headers=HEADERS_XAPI, params=params, timeout=45)
    raw = r.text
    try:
        body = r.json()
    except Exception:
        body = {"_raw": raw}
    if r.status_code >= 400:
        st.error(f"[GET {url}] {r.status_code}: {raw}")
        r.raise_for_status()
    return r.status_code, body, raw

def _post_xapi(url, payload=None):
    r = requests.post(url, headers=HEADERS_XAPI, data=json.dumps(payload or {}), timeout=60)
    raw = r.text
    try:
        body = r.json()
    except Exception:
        body = {"_raw": raw}
    if r.status_code >= 400:
        st.error(f"[POST {url}] {r.status_code}: {raw}")
        r.raise_for_status()
    return r.status_code, body, raw

def _post_bearer(url, token, payload=None):
    r = requests.post(url, headers=headers_bearer(token), data=json.dumps(payload or {}), timeout=60)
    raw = r.text
    try:
        body = r.json()
    except Exception:
        body = {"_raw": raw}
    if r.status_code >= 400:
        st.error(f"[POST {url}] {r.status_code}: {raw}")
        r.raise_for_status()
    return r.status_code, body, raw

# ---------- Avatars (ACTIVE only) ----------
@st.cache_data(ttl=300)
def fetch_interactive_avatars():
    _, body, _ = _get(API_LIST_AVATARS)
    data = body.get("data") or []
    items = []
    for a in data:
        if isinstance(a, dict) and a.get("status") == "ACTIVE":
            items.append({
                "label": a.get("pose_name") or a.get("avatar_id"),
                "avatar_id": a.get("avatar_id"),
                "default_voice": a.get("default_voice"),
            })
    # dedupe
    seen, out = set(), []
    for it in items:
        aid = it.get("avatar_id")
        if aid and aid not in seen:
            seen.add(aid)
            out.append(it)
    return out

avatars = fetch_interactive_avatars()
if not avatars:
    st.error("No ACTIVE interactive avatars returned by HeyGen.")
    st.stop()

names = [a["label"] for a in avatars]
choice = st.selectbox("Choose an avatar", names, index=0)
selected = next(a for a in avatars if a["label"] == choice)

# ---------- Session helpers ----------
def new_session(avatar_id: str):
    """Return (session_id, offer_sdp)."""
    _, body, _ = _post_xapi(API_STREAM_NEW, {"avatar_id": avatar_id})
    data = body.get("data") or {}
    sid = data.get("session_id")
    offer = (data.get("offer") or {}).get("sdp")
    if not sid or not offer:
        raise RuntimeError(f"Missing session_id or offer in response: {body}")
    return sid, offer

def create_session_token(session_id: str) -> str:
    _, body, _ = _post_xapi(API_CREATE_TOKEN, {"session_id": session_id})
    tok = (body.get("data") or {}).get("token") or (body.get("data") or {}).get("access_token")
    if not tok:
        raise RuntimeError(f"Missing token in response: {body}")
    return tok

def send_echo(session_id: str, session_token: str, text: str):
    _post_bearer(API_STREAM_TASK, session_token, {
        "session_id": session_id,
        "task_type": "repeat",
        "task_mode": "sync",
        "text": text
    })

def stop_session(session_id: str, session_token: str):
    try:
        _post_bearer(API_STREAM_STOP, session_token, {"session_id": session_id})
    except Exception:
        pass

# ---------- Streamlit state ----------
ss = st.session_state
ss.setdefault("session_id", None)
ss.setdefault("session_token", None)
ss.setdefault("offer_sdp", None)

# ---------- Controls ----------
c1, c2 = st.columns(2)
with c1:
    if st.button("Start / Restart", use_container_width=True):
        if ss.session_id and ss.session_token:
            stop_session(ss.session_id, ss.session_token)
            time.sleep(0.2)

        sid, offer_sdp = new_session(selected["avatar_id"])
        tok = create_session_token(sid)

        # small delay like your test5.py; also helps Streamlit Cloud iframes
        time.sleep(1.0)

        ss.session_id = sid
        ss.session_token = tok
        ss.offer_sdp = offer_sdp

with c2:
    if st.button("Stop", type="secondary", use_container_width=True):
        if ss.session_id and ss.session_token:
            stop_session(ss.session_id, ss.session_token)
        ss.session_id = None
        ss.session_token = None
        ss.offer_sdp = None

# ---------- Viewer embed (pure WebRTC; no SDK) ----------
viewer_path = Path(__file__).parent / "viewer.html"
if not viewer_path.exists():
    st.warning("viewer.html not found next to streamlit_app.py.")
else:
    if ss.session_id and ss.session_token and ss.offer_sdp:
        html = (
            viewer_path.read_text(encoding="utf-8")
            .replace("__SESSION_TOKEN__", ss.session_token)
            .replace("__AVATAR_NAME__", selected["label"])
            .replace("__SESSION_ID__", ss.session_id)
            .replace("__OFFER_SDP__", json.dumps(ss.offer_sdp)[1:-1])  # keep raw newlines
        )
        components.html(html, height=640, scrolling=True)
    else:
        st.info("Click **Start / Restart** to open a session and load the viewer.")

# ---------- Echo buttons ----------
st.write("---")
b1, b2, b3 = st.columns(3)
def _need_session():
    return not (ss.session_id and ss.session_token and ss.offer_sdp)

with b1:
    if st.button("Test-1", use_container_width=True):
        if _need_session():
            st.warning("Start a session first.")
        else:
            send_echo(ss.session_id, ss.session_token,
                      "Hello. Welcome to the test demonstration.")

with b2:
    if st.button("Test-2", use_container_width=True):
        if _need_session():
            st.warning("Start a session first.")
        else:
            send_echo(ss.session_id, ss.session_token,
                      "I can talk in any language and also connect to Chat GPT.")

with b3:
    if st.button("测试3", use_container_width=True):
        if _need_session():
            st.warning("Start a session first.")
        else:
            send_echo(ss.session_id, ss.session_token,
                      "反馈我普通话发音是否正确。")

