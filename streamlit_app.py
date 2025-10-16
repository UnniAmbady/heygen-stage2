# Hey Gen-Stage.2-Ver.2
# from openai import OpenAI
import json
import time
from pathlib import Path

import requests
import streamlit as st
import streamlit.components.v1 as components

# ---------- Config: mobile-first, no sidebar ----------
st.set_page_config(page_title="AI Avatar Demo", layout="centered")
st.title("AI Avatar Demo")

# Secrets
OPENAI_API_KEY = st.secrets["openai"]["secret_key"]
HEYGEN_API_KEY = st.secrets["HeyGen"]["heygen_api_key"]

# ---------- Endpoints & Headers (per HeyGen docs) ----------
BASE = "https://api.heygen.com/v1"
API_LIST_AVATARS = f"{BASE}/streaming/avatar.list"   # GET
API_STREAM_NEW   = f"{BASE}/streaming.new"           # POST
API_CREATE_TOKEN = f"{BASE}/streaming.create_token"  # POST
API_STREAM_START = f"{BASE}/streaming.start"         # POST
API_STREAM_TASK  = f"{BASE}/streaming.task"          # POST
API_STREAM_STOP  = f"{BASE}/streaming.stop"          # POST

HEADERS = {
    "accept": "application/json",
    "x-api-key": HEYGEN_API_KEY,
    "Content-Type": "application/json",
}

# ---------- Small HTTP helpers that *show* error bodies ----------
def _get(url, params=None):
    r = requests.get(url, headers=HEADERS, params=params, timeout=45)
    raw = r.text
    try:
        body = r.json()
    except Exception:
        body = {"_raw": raw}
    if r.status_code >= 400:
        # Show server message in Streamlit *before* raising
        st.error(f"[GET {url}] {r.status_code}: {raw}")
        r.raise_for_status()
    return r.status_code, body, raw

def _post(url, payload=None):
    data = json.dumps(payload or {})
    r = requests.post(url, headers=HEADERS, data=data, timeout=60)
    raw = r.text
    try:
        body = r.json()
    except Exception:
        body = {"_raw": raw}
    if r.status_code >= 400:
        st.error(f"[POST {url}] {r.status_code}: {raw}")
        r.raise_for_status()
    return r.status_code, body, raw

# ---------- REST: fetch interactive avatars (parse `data` array) ----------
@st.cache_data(ttl=300)
def fetch_interactive_avatars():
    status, body, raw = _get(API_LIST_AVATARS)
    # Per docs, response is {"code":100,"data":[ ... ], "message":"Success"}
    data = body.get("data") or []
    items = []
    for a in data:
        if not isinstance(a, dict):
            continue
        if a.get("status") == "ACTIVE":
            items.append({
                "label": a.get("pose_name") or a.get("avatar_id"),
                "avatar_id": a.get("avatar_id"),
                "default_voice": a.get("default_voice"),
                "preview": a.get("normal_preview"),
                "is_public": a.get("is_public"),
            })
    # dedupe by avatar_id
    seen, out = set(), []
    for it in items:
        aid = it.get("avatar_id")
        if aid and aid not in seen:
            seen.add(aid)
            out.append(it)
    return out

avatars = fetch_interactive_avatars()
if not avatars:
    st.error("No ACTIVE interactive avatars returned by HeyGen. Check account access or plan.")
    st.stop()

# ---------- UI: dropdown (use real names / pose_name; no 'Avatar 1/2/3') ----------
name_options = [a["label"] for a in avatars]
choice = st.selectbox("Choose an avatar", name_options, index=0)
selected = next(a for a in avatars if a["label"] == choice)

# ---------- Session helpers ----------
def create_session(avatar_id: str) -> str:
    # Minimal payload; let HeyGen pick defaults. You can add 'voice', 'camera', etc.
    payload = {"avatar_id": avatar_id}
    _, body, _ = _post(API_STREAM_NEW, payload)
    sid = (body.get("data") or {}).get("session_id")
    if not sid:
        raise RuntimeError(f"Missing session_id in response: {body}")
    return sid

def create_session_token(session_id: str) -> str:
    _, body, _ = _post(API_CREATE_TOKEN, {"session_id": session_id})
    tok = (body.get("data") or {}).get("token")
    if not tok:
        raise RuntimeError(f"Missing token in response: {body}")
    return tok

def start_session(session_id: str):
    # Some accounts need a short delay after new → token before start.
    time.sleep(0.25)
    _post(API_STREAM_START, {"session_id": session_id})

def send_echo(session_id: str, text: str):
    # TaskType.REPEAT echoes the exact text (lowest latency for your tests)
    _post(API_STREAM_TASK, {"session_id": session_id, "task_type": "repeat", "text": text})

def stop_session(session_id: str):
    try:
        _post(API_STREAM_STOP, {"session_id": session_id})
    except Exception:
        pass

# ---------- Streamlit session state ----------
if "session_id" not in st.session_state:
    st.session_state.session_id = None
if "session_token" not in st.session_state:
    st.session_state.session_token = None

# ---------- Controls ----------
col1, col2 = st.columns(2)
with col1:
    if st.button("Start / Restart", use_container_width=True):
        # Cleanup old
        if st.session_state.session_id:
            stop_session(st.session_state.session_id)
            time.sleep(0.2)

        # Create → Token → Start (consistent headers)
        sid = create_session(selected["avatar_id"])
        tok = create_session_token(sid)
        start_session(sid)

        st.session_state.session_id = sid
        st.session_state.session_token = tok

with col2:
    if st.button("Stop", type="secondary", use_container_width=True):
        if st.session_state.session_id:
            stop_session(st.session_state.session_id)
        st.session_state.session_id = None
        st.session_state.session_token = None

# ---------- Viewer embed ----------
viewer_path = Path(__file__).parent / "viewer.html"
if not viewer_path.exists():
    st.warning("viewer.html not found. Add the file next to streamlit_app.py (see code below).")
else:
    if st.session_state.session_id and st.session_state.session_token:
        src = (
            viewer_path.read_text(encoding="utf-8")
            .replace("__SESSION_TOKEN__", st.session_state.session_token)
            .replace("__AVATAR_NAME__", selected["label"])
        )
        components.html(src, height=520, scrolling=False)
    else:
        st.info("Click **Start / Restart** to open a session and load the viewer.")

# ---------- Echo buttons ----------
st.write("---")
c1, c2, c3 = st.columns(3)

def _need_session():
    return not (st.session_state.session_id and st.session_state.session_token)

with c1:
    if st.button("Test-1", use_container_width=True):
        if _need_session():
            st.warning("Start a session first.")
        else:
            send_echo(st.session_state.session_id, "Hello. Welcome to the test demonstration.")

with c2:
    if st.button("Test-2", use_container_width=True):
        if _need_session():
            st.warning("Start a session first.")
        else:
            send_echo(st.session_state.session_id, "I can talk in any language and also connect to Chat GPT.")

with c3:
    if st.button("测试3", use_container_width=True):
        if _need_session():
            st.warning("Start a session first.")
        else:
            send_echo(st.session_state.session_id, "反馈我普通话发音是否正确。")

