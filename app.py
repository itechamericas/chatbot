
import os
import io
import time
import base64
import requests
import streamlit as st

BACKEND_URL = os.getenv("BACKEND_URL", "https://localhost:9000")
API_KEY = os.getenv("INTERNAL_API_KEY", "")

st.set_page_config(page_title="iTech Americas – AI Assistant", page_icon="🤖", layout="wide")

# --- Header ---
left, right = st.columns([1,1])
with left:
    st.title("🤖 iTech Americas – AI Assistant")
with right:
    st.write("")
    st.caption("Powered by RAG + Voice (STT/TTS)")

# --- Sidebar: settings ---
st.sidebar.header("Settings")
backend_url = st.sidebar.text_input("Backend URL", BACKEND_URL)
api_key = st.sidebar.text_input("API Key (x-api-key)", API_KEY, type="password")
voice_name = st.sidebar.text_input("TTS Voice", "alloy")
session_id = st.sidebar.text_input("Session ID", "default")
st.sidebar.markdown("---")
if st.sidebar.button("Ping Backend"):
    try:
        r = requests.get(backend_url, timeout=10, verify=False)
        st.sidebar.success(f"Backend reachable: {r.status_code}")
    except Exception as e:
        st.sidebar.error(f"Error: {e}")

st.sidebar.markdown("---")
st.sidebar.caption("Export")
if st.sidebar.button("Download messages.csv"):
    try:
        r = requests.get(f"{backend_url}/export/messages.csv", headers={"x-api-key": api_key}, timeout=30, verify=False)
        if r.ok:
            st.sidebar.download_button("Save CSV", r.content, file_name="messages_export.csv")
        else:
            st.sidebar.error(f"Export failed: {r.status_code}")
    except Exception as e:
        st.sidebar.error(f"Export error: {e}")

# --- Tabs ---
tab_chat, tab_voice, tab_knowledge, tab_insights = st.tabs(["💬 Chat", "🎙️ Voice", "📚 Knowledge", "📈 Insights"])

# --- Chat Tab ---
with tab_chat:
    st.subheader("Chat")
    if "messages" not in st.session_state:
        st.session_state.messages = []  # [{'user': 'Hi', 'bot': 'Hello', 'id': 1}, ...]

    prompt = st.text_area("Your message", height=100, placeholder="Ask anything about your services, company info, etc.")
    col1, col2, col3 = st.columns([1,1,2])
    with col1:
        send_btn = st.button("Send", use_container_width=True)
    with col2:
        clear_btn = st.button("Clear chat", use_container_width=True)

    if clear_btn:
        st.session_state.messages = []
        st.experimental_rerun()

    def render_message(idx, m):
        with st.container():
            st.markdown(f"**You:** {m['user']}")
            st.markdown(f"**Bot:** {m['bot']}")
            c1, c2, c3 = st.columns([1,1,6])
            with c1:
                if st.button("👍", key=f"up_{idx}"):
                    try:
                        if m.get("id"):
                            requests.post(f"{backend_url}/feedback", headers={"x-api-key": api_key}, json={"message_id": m["id"], "rating": 1}, timeout=10, verify=False)
                            st.success("Thanks for the feedback!")
                    except Exception as e:
                        st.error(f"Feedback error: {e}")
            with c2:
                if st.button("👎", key=f"down_{idx}"):
                    try:
                        if m.get("id"):
                            requests.post(f"{backend_url}/feedback", headers={"x-api-key": api_key}, json={"message_id": m["id"], "rating": -1}, timeout=10, verify=False)
                            st.info("Feedback saved.")
                    except Exception as e:
                        st.error(f"Feedback error: {e}")

    if send_btn and prompt.strip():
        try:
            r = requests.post(f"{backend_url}/chat", headers={"x-api-key": api_key}, json={"message": prompt, "session_id": session_id}, timeout=60, verify=False)
            if r.ok:
                data = r.json()
                # Expected keys: response, message_id
                bot_text = data.get("response") or data.get("answer") or ""
                msg_id = data.get("message_id")
                st.session_state.messages.append({"user": prompt, "bot": bot_text, "id": msg_id})
            else:
                st.error(f"Chat error: {r.status_code} {r.text}")
        except Exception as e:
            st.error(f"Request failed: {e}")

    st.markdown("---")
    for i, m in enumerate(st.session_state.messages):
        render_message(i, m)

# --- Voice Tab ---
with tab_voice:
    st.subheader("Talk to the bot")
    st.caption("Upload a short audio (mp3/m4a/wav/webm). You'll get text + a spoken reply.")
    file = st.file_uploader("Audio file", type=["mp3","wav","m4a","webm"])

    if st.button("Send voice message") and file is not None:
        try:
            files = {"file": (file.name, file.getvalue(), file.type)}
            data = {"session_id": session_id, "voice": voice_name}
            r = requests.post(f"{backend_url}/chat/voice", headers={"x-api-key": api_key}, files=files, data=data, timeout=120, verify=False)
            if r.ok:
                data = r.json()
                st.markdown(f"**Transcript:** {data.get('transcript','')}")
                st.markdown(f"**Response:** {data.get('response_text','')}")
                audio_b64 = data.get("response_audio_b64","")
                if audio_b64:
                    st.audio(base64.b64decode(audio_b64), format="audio/mp3")
            else:
                st.error(f"Voice chat error: {r.status_code}")
        except Exception as e:
            st.error(f"Voice request failed: {e}")

    st.markdown("— or —")
    st.caption("If you just want transcription:")
    file2 = st.file_uploader("Transcribe only", key="transcribe_only", type=["mp3","wav","m4a","webm"])
    if st.button("Transcribe"):
        if file2:
            try:
                files = {"file": (file2.name, file2.getvalue(), file2.type)}
                r = requests.post(f"{backend_url}/audio/transcribe", files=files, timeout=120, verify=False)
                st.success(r.json())
            except Exception as e:
                st.error(f"Transcribe error: {e}")
        else:
            st.warning("Please upload an audio file.")

# --- Knowledge Tab ---
with tab_knowledge:
    st.subheader("Add knowledge (incremental)")
    st.caption("Paste helpful Q&A, policy, or notes below to teach the assistant without a full rebuild.")
    kb_text = st.text_area("Document text", height=200, placeholder="Q: ...\nA: ...")
    source = st.text_input("Source label", "runtime_notes.txt")

    if st.button("Add to FAISS index"):
        if kb_text.strip():
            try:
                # We'll call a small /ingest/text endpoint if it exists;
                # If not present on backend, we fallback to /chat with a special directive.
                # Prefer direct ingest endpoint if you implement it, otherwise backend can listen for this special key.
                r = requests.post(f"{backend_url}/ingest/text", headers={"x-api-key": api_key}, json={"text": kb_text, "source": source}, timeout=60, verify=False)
                if r.ok:
                    st.success("Added to index.")
                else:
                    st.info("Backend doesn't have /ingest/text yet. Try the temporary workaround:")
                    st.code("from faiss_index import add_document_to_faiss\nadd_document_to_faiss(text, source)", language="python")
            except Exception as e:
                st.error(f"Ingest error: {e}")
        else:
            st.warning("Please paste some content.")

# --- Insights Tab ---
with tab_insights:
    st.subheader("Export & basic stats")
    st.caption("Download CSV from the sidebar. Below is a quick pulse if the backend exposes a stats endpoint.")
    try:
        r = requests.get(f"{backend_url}/stats", headers={"x-api-key": api_key}, timeout=10, verify=False)
        if r.ok:
            stats = r.json()
            st.json(stats)
        else:
            st.info("No /stats endpoint on backend (optional).")
    except Exception as e:
        st.info("Stats unavailable.")
