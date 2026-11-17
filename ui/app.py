import os
import time
import uuid

import streamlit as st

import agent_client as ac

CLIENT_ID = os.environ.get("CLIENT_ID")
RUNTIME_ARN = os.environ.get("RUNTIME_ARN")

st.set_page_config(page_title="Research Paper Assistant", page_icon="📚")

missing = [n for n, v in [("CLIENT_ID", CLIENT_ID), ("RUNTIME_ARN", RUNTIME_ARN)] if not v]
if missing:
    st.error(f"Missing environment variables: {', '.join(missing)}. Load .env first.")
    st.stop()

state = st.session_state
state.setdefault("tokens", None)
state.setdefault("username", None)
state.setdefault("session_id", str(uuid.uuid4()))
state.setdefault("messages", [])


def sign_out():
    for key in ("tokens", "username", "messages"):
        state.pop(key, None)
    state.session_id = str(uuid.uuid4())
    st.rerun()


def access_token():
    """The current access token, renewed shortly before it expires."""
    tokens = state.tokens
    if tokens["expires_at"] - time.time() < 120:
        try:
            state.tokens = ac.refresh(CLIENT_ID, tokens["refresh"])
        except Exception:
            sign_out()
    return state.tokens["access"]


# ---------------------------------------------------------------- sign-in
if not state.tokens:
    st.title("📚 Research Paper Assistant")
    with st.form("login"):
        username = st.text_input("Username")
        password = st.text_input("Password", type="password")
        if st.form_submit_button("Sign in"):
            try:
                state.tokens = ac.sign_in(CLIENT_ID, username, password)
                state.username = username
                st.rerun()
            except Exception as e:
                st.error(f"Sign-in failed: {e}")
    st.stop()

# ---------------------------------------------------------------- sidebar
with st.sidebar:
    st.write(f"Signed in as **{state.username}**")
    if st.button("New conversation"):
        state.session_id = str(uuid.uuid4())
        state.messages = []
        st.rerun()
    if st.button("Sign out"):
        sign_out()
    st.caption(f"Session `{state.session_id[:8]}…`")

# ---------------------------------------------------------------- chat
st.title("📚 Research Paper Assistant")
for message in state.messages:
    with st.chat_message(message["role"]):
        if message.get("tools"):
            st.caption("🔧 " + ", ".join(message["tools"]))
        st.markdown(message["content"])

if prompt := st.chat_input("Ask about papers…"):
    state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    with st.chat_message("assistant"):
        notice, box = st.empty(), st.empty()
        text, tools = "", []
        try:
            for kind, value in ac.stream_chat(RUNTIME_ARN, access_token(), state.session_id, prompt):
                if kind == "tool":
                    tools.append(value.split("___")[-1])
                    notice.caption("🔧 " + ", ".join(tools))
                else:
                    text += value
                    box.markdown(ac.clean_thinking(text) + "▌")
            answer = ac.clean_thinking(text) or "(no answer)"
        except Exception as e:
            answer = f"⚠️ {e}"
        box.markdown(answer)

    state.messages.append({"role": "assistant", "content": answer, "tools": tools})
    st.rerun()
