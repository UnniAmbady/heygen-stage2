# Hey Gen-Stage-2
# from openai import OpenAI

import os
import json
import time
import requests
import streamlit as st
import streamlit.components.v1 as components
from pathlib import Path

# ---- CONFIG (mobile-friendly, no sidebar) ----
st.set_page_config(page_title="AI Avatar Demo", layout="centered")
st.title("AI Avatar Demo")

OPENAI_API_KEY   = st.secrets["openai"]["secret_key"]
HEYGEN_API_KEY   = st.secrets["HeyGen"]["heygen_api_key"]

HEADERS = {"Authorization": f"Bearer {HEYGEN_API_KEY}", "Content-Type": "application/json"}

API_LIST_AVATARS   = "https://api.heygen.com/v1/streaming/avatar.list"   # list interactive avatars
API_STREAM_NEW     = "https://api.heygen.com/v1/streaming.new"           # create session
API_CREATE_TOKEN   = "https://api.heygen.com/v1/streaming.create_token"  # session token
API_STREAM_START   = "https://api.heygen.com/v1/streaming.start"         # start session
API_STREAM_TASK    = "https://api.heygen.com/v1/streaming.task"          # speak text
API_STREAM_STOP    = "https://api.heygen.com/v1/streaming.stop"          # stop session

@st.cache_data(ttl=300)
def fetch_avatars():
    r = requests.get(API_LIST_AVATARS, headers=HEADERS, timeout=30)
    r.raise_for_status()
    data = r.json().get("data", {})
    # Normalize: list may be under "avatars" or "list" depending on account
    items = data.get("list") or data.get("avatars") or []
    # Keep only essentials for dropdown
    return [
        {"id": item.get("id") or item.get("avatar_id"),
         "name": item.get("name") or item.get("avatar_name") or f"Avatar {idx+1}"}
        for idx, item in enumerate(items)
        if (item.get("id") or item.get("avatar_id"))
    ]

avatars = fetch_avatars()
if not avatars:
    st.error("No Interactive Avatars found on your account. Create or enable one in HeyGen first.")
    st.stop()

# ---- UI: Avatar selection (name only, no preview) ----
names = [a["name"] for a in avatars]
choice = st.selectbox("Choose an avatar", names, index=0)

selected = next(a for a in avatars if a["name"] == choice)

# ---- Create/Start session helpers ----
def create_session(avatar_id: str):
    payload = {
        # Most accounts accept either avatar_id or avatar_name. Prefer ID.
        "avatar_id": avatar_id,
        "quality": "high",
        # Keep the mic muted on the viewer; we'll drive it by tasks
        "config": {"voice": {"rate": 1.0}, "camera": {"background": "transparent"}}
    }
    r = requests.post(API_STREAM_NEW, headers=HEADERS, data=json.dumps(payload), timeout=60)
    r.raise_for_status()
    return r.json()["data"]["session_id"]

def create_session_token(session_id: str):
    payload = {"session_id": session_id}
    r = requests.post(API_CREATE_TOKEN, headers=HEADERS, data=json.dumps(payload), timeout=30)
    r.raise_for_status()
    return r.json()["data"]["token"]

def start_session(session_id: str):
    payload = {"session_id": session_id}
    r = requests.post(API_STREAM_START, headers=HEADERS, data=json.dumps(payload), timeout=30)
    r.raise_for_status()
    return r.json()

def send_echo(session_id: str, text: str):
    # TaskType.REPEAT (echo the exact text) is the simplest low-latency mode
    payload = {"session_id": session_id, "task_type": "repeat", "text": text}
    r = requests.post(API_STREAM_TASK, headers=HEADERS, data=json.dumps(payload), timeout=30)
    r.raise_for_status()
    return r.json()

def stop_session(session_id: str):
    try:
        requests.post(API_STREAM_STOP, headers=HEADERS, data=json.dumps({"session_id": session_id}), timeout=15)
    except Exception:
        pass

# ---- SESSION STATE ----
if "session_id" not in st.session_state:
    st.session_state.session_id = None
if "session_token" not in st.session_state:
    st.session_state.session_token = None
if "avatar_id" not in st.session_state:
    st.session_state.avatar_id = None

col_start, col_stop = st.columns(2)
with col_start:
    if st.button("Start / Restart", use_container_width=True):
        # Clean up previous session
        if st.session_state.session_id:
            stop_session(st.session_state.session_id)
            time.sleep(0.3)

        session_id = create_session(selected["id"])
        token      = create_session_token(session_id)
        start_session(session_id)

        st.session_state.session_id   = session_id
        st.session_state.session_token = token
        st.session_state.avatar_id    = selected["id"]

with col_stop:
    if st.button("Stop Session", use_container_width=True, type="secondary"):
        if st.session_state.session_id:
            stop_session(st.session_state.session_id)
        st.session_state.session_id = None
        st.session_state.session_token = None

# ---- Interactive frame (viewer.html) below the dropdown ----
viewer_path = Path(__file__).parent / "viewer.html"
if not viewer_path.exists():
    st.warning("viewer.html not found next to app.py. Create it using the code below.")
else:
    if st.session_state.session_id and st.session_state.session_token:
        # Pass session_token & avatar name to viewer via URL search params
        # (the viewer will use HeyGen Streaming SDK to attach to the live stream)
        src = (
            viewer_path.read_text(encoding="utf-8")
            .replace("__SESSION_TOKEN__", st.session_state.session_token)
            .replace("__AVATAR_NAME__", choice)
        )
        components.html(src, height=520, scrolling=False)
    else:
        st.info("Click **Start / Restart** to open a live session and display the viewer.")

# ---- Echo buttons ----
st.write("---")
c1, c2, c3 = st.columns(3)

def _needs_session():
    return not (st.session_state.session_id and st.session_state.session_token)

with c1:
    if st.button("Test-1", use_container_width=True):
        if _needs_session():
            st.warning("Please start a session first.")
        else:
            send_echo(st.session_state.session_id, "Hello. Welcome to the test demonstration.")

with c2:
    if st.button("Test-2", use_container_width=True):
        if _needs_session():
            st.warning("Please start a session first.")
        else:
            send_echo(st.session_state.session_id, "I can talk in any language and also connect to Chat GPT.")

with c3:
    if st.button("测试3", use_container_width=True):
        if _needs_session():
            st.warning("Please start a session first.")
        else:
            send_echo(st.session_state.session_id, "反馈我普通话发音是否正确。")
