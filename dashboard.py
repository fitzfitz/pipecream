from pathlib import Path
import streamlit as st
from db import init_db, create_job, list_jobs, update_job

st.set_page_config(page_title="M5 AI Video Factory", layout="wide")
init_db()

st.title("🎬 Autonomous M5 AI Video Factory")

with st.sidebar:
    st.header("➕ Queue New Video")
    mode = st.radio("Topic Source", ["Auto-Scrape Reddit", "Custom Topic / Idea"])
    subreddit = st.text_input("Subreddit", value="UnresolvedMysteries") if mode == "Auto-Scrape Reddit" else "Custom"
    custom_topic = st.text_area("Custom Story Prompt") if mode == "Custom Topic / Idea" else None
    auto_mode = st.toggle("Full Auto-Pilot (Skip Script Approval)", value=True)

    if st.button("🚀 Launch Video Job", use_container_width=True):
        job_id = create_job(subreddit=subreddit, topic_title=custom_topic, auto_mode=1 if auto_mode else 0)
        st.success(f"Job #{job_id} queued!")
        st.rerun()

    if st.button("🔄 Refresh Status", use_container_width=True):
        st.rerun()

tab1, tab2, tab3 = st.tabs(["📊 Live Pipeline Queue", "✍️ Script Review (Human-in-the-Loop)", "🎥 Completed Videos"])

jobs = list_jobs()

with tab1:
    if not jobs:
        st.info("No jobs yet. Use the sidebar to launch your first autonomous short!")
    for j in jobs:
        with st.expander(f"Job #{j['id']} — {j['topic_title'] or 'Picking topic...'} [{j['status']}]", expanded=j["status"] not in ("COMPLETED", "FAILED")):
            st.write(f"**Status:** `{j['status']}` | **Source:** {j['source_url'] or j['subreddit']}")
            if j["error_msg"]:
                st.error(j["error_msg"])
                if st.button(f"Retry Job #{j['id']}", key=f"retry_{j['id']}"):
                    update_job(j["id"], status="QUEUED", error_msg=None)
                    st.rerun()

with tab2:
    waiting = [j for j in jobs if j["status"] == "WAITING_SCRIPT_APPROVAL"]
    if not waiting:
        st.info("No scripts waiting for approval.")
    for j in waiting:
        st.subheader(f"Job #{j['id']}: {j['topic_title']}")
        edited_json = st.text_area("Edit Script & Visual Prompts (JSON)", value=j["script_json"], height=320, key=f"edit_{j['id']}")
        if st.button("✅ Approve & Render Video", key=f"app_{j['id']}"):
            update_job(j["id"], script_json=edited_json, status="APPROVED_FOR_MEDIA")
            st.success("Sent to M5 Media Pipeline!")
            st.rerun()

with tab3:
    completed = [j for j in jobs if j["status"] == "COMPLETED" and j["video_path"]]
    cols = st.columns(3)
    for idx, j in enumerate(completed):
        with cols[idx % 3]:
            st.markdown(f"**#{j['id']}: {j['topic_title']}**")
            vpath = Path(j["video_path"])
            if vpath.exists():
                st.video(str(vpath))
