import hashlib
from datetime import datetime

import streamlit as st
from dotenv import load_dotenv
from PIL import Image
from streamlit_feedback import streamlit_feedback

from webapp.helpers_webapp import (
    ENVIRONMENT,
    FailSavingChat,
    chain_rag,
    init_app,
    log_result_to_MS_teams,
    process_feedback,
    save_chat,
    set_styling,
)

load_dotenv()

INITIAL_MESSAGES = [{"role": "assistant", "content": "Waar kan ik je mee helpen?"}]

set_styling()
init_app()

st.markdown("# Vraag het aan Ally")


def init_chain_rag(k: int):
    """Initialize RAG chain using k chunks."""
    st.session_state["logger"].debug("Initializing RAG chain (in chat-app).")
    return chain_rag(llm=st.session_state["llm"], vectorindex=st.session_state["vectorstore"], k=k)


# Sidebar & reset


def reset_history():
    """Clear chat history."""
    st.session_state["chain_rag"] = chain_rag(
        llm=st.session_state["llm"],
        vectorindex=st.session_state["vectorstore"],
        k=st.session_state.search_k,
    )
    st.session_state.messages = INITIAL_MESSAGES
    st.session_state["feedback_key"] = None


def send_feedback(context: dict):
    """Send the feedback to Teams and to Datalake."""

    # Format chat history for readability
    chat_history_str = ""
    for i, msg in enumerate(st.session_state.get("messages", []), 1):
        chat_line = f"{i}. Rol: {msg['role']}\n   Bericht: {msg['content']}"
        if "source_titles" in msg and "urls" in msg:
            chat_line += "\n    **Bronnen**:"
            for j, src_title in enumerate(msg["source_titles"]):
                chat_line += f"\n     - {src_title} ({msg['urls'][j]})"
        chat_history_str += chat_line + "\n\n"
    message = f"**Duim:** {context['rating']}\n**Feedback:**\n{context['comment']}\n**Chatgeschiedenis:**\n{chat_history_str.strip()}"  # noqa: E501

    log_result_to_MS_teams(result=message, otap=ENVIRONMENT)


with st.sidebar:
    st.image(Image.open("./src/webapp/img/ALG_RGB_Robothuis.png"))
    st.write(
        "Ally zal proberen je vragen te beantwoorden. Daarbij worden de meest relevante documenten uit de \
        kennisbank gebruikt."
    )
    st.sidebar.selectbox("Hoeveel documenten wil je gebruiken?", (4, 3, 5, 7), key="search_k")
    st.write("Druk op de knop hieronder om een nieuwe chat te starten.")
    st.button("Start nieuwe chat", on_click=reset_history)

# Take care of feedback (if present)

if "feedback_key" not in st.session_state:
    st.session_state["feedback_key"] = None


if st.session_state["feedback_key"] is not None:
    key = st.session_state["feedback_key"]
    feedback_dict = st.session_state.get(key, None)
    if feedback_dict is not None:
        user_feedback = {
            "environment": ENVIRONMENT,
            "app": "chat",
            "session_uuid": st.session_state["session_uuid"],
            "timestamp_feedback": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "user_question": st.session_state["messages"][-2]["content"],
            "assistant_answer": st.session_state["messages"][-1]["content"],
            "conversation": st.session_state["messages"],
            "feedback_score": "thumbs_down" if st.session_state[key]["score"] == "👎" else "thumbs_up",
            "feedback_text": st.session_state[key]["text"],
        }
        try:
            send_feedback({"rating": user_feedback["feedback_score"], "comment": user_feedback["feedback_text"]})
            process_feedback(client=st.session_state["blob_client"], user_feedback=user_feedback, type_feedback="chat")
        except Exception as e:
            st.session_state["logger"].error(f"Opslaan van feedback is niet gelukt: {e}")
        st.toast("Bedankt voor je feedback!")
        st.session_state["logger"].debug(f"Feedback: {user_feedback}")
        try:
            del st.session_state[key]
            aux_key = f"feedback_submitted_{key}"
            del st.session_state[aux_key]
        except Exception as e:
            st.session_state["logger"].error(repr(e))
    st.session_state["feedback_key"] = None


# Intialize RAG-chain and messages

if "chain_rag" not in st.session_state:
    st.session_state["chain_rag"] = init_chain_rag(st.session_state.search_k)

if "messages" not in st.session_state:
    st.session_state.messages = INITIAL_MESSAGES

if "user" not in st.session_state:
    st.session_state.user = {}

if "UserPrincipalName" not in st.session_state.user or st.session_state.user["UserPrincipalName"] == "":
    headers = st.context.headers
    user_email = headers.get("X-Ms-Client-Principal-Name")

    if user_email:
        st.session_state.user["userPrincipalName"] = user_email
    else:
        st.session_state.user["userPrincipalName"] = ""


# Chat
for message in st.session_state.messages:
    # print chat history (recall that streamlit refreshes the page on every interaction)
    if message["role"] == "assistant":
        content = message["content"] + "\n\n"
        for i in range(len(message.get("source_titles", []))):
            title = message["source_titles"][i]
            url = message["urls"][i]
            content += f"[{i + 1}. {title}]({url})  \n"
        st.chat_message("assistant", avatar=Image.open("./src/webapp/img/icon-robot.png")).write(content)
    else:
        st.chat_message(message["role"], avatar=Image.open("./src/webapp/img/icon-chat.png")).write(message["content"])


if prompt := st.chat_input(placeholder="Stel je vraag hier"):
    st.chat_message("user", avatar=Image.open("./src/webapp/img/icon-chat.png")).write(prompt)
    st.session_state.messages.append({"role": "user", "content": prompt})


if len(st.session_state.messages) > 1 and st.session_state.messages[-1]["role"] != "assistant":
    with st.chat_message("assistant", avatar=Image.open("./src/webapp/img/icon-robot.png")):
        with st.spinner("Nadenken..."):
            try:
                result = st.session_state.chain_rag({"question": prompt})
                answer = result["answer"] + "\n\n"
                urls = []
                source_titles = []
                for j, source_document in enumerate(result["source_documents"]):
                    motivation = f"""{1 + j}: {source_document.metadata['source']}"""
                    url = source_document.metadata["url"]
                    answer += f"[{motivation}]({url})  \n"
                    urls.append(source_document.metadata["url"])
                    source_titles.append(source_document.metadata["source"])
                st.write(answer)

                message = {
                    "role": "assistant",
                    "content": result["answer"],
                    "source_titles": source_titles,
                    "urls": urls,
                }
                st.session_state.messages.append(message)
                try:
                    chat = {
                        "environment": ENVIRONMENT,
                        "session_uuid": st.session_state["session_uuid"],
                        "timestamp_last_chat": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        "conversation": st.session_state["messages"],
                        "hashed_user": hashlib.sha512(
                            st.session_state.user["userPrincipalName"].encode("utf-8")
                        ).hexdigest(),
                    }
                    save_chat(client=st.session_state["blob_client"], chat=chat)
                except Exception as e:
                    raise FailSavingChat(message=f"Opslaan van chat is niet gelukt: {repr(e)}")
            except Exception as e:
                st.write("**Er is iets misgegaan.** Refresh je browser en kijk of het probleem nogmaals optreedt.")
                st.write(
                    (
                        "Treedt het probleem nogmaals op? Gelieve dan een screenshot maken van de gestelde vraag, het "
                        "eventuele antwoord en kopieer onderstaande foutmelding. Stuur dit naar het DCC: "
                        "dcc@de-alliantie.nl."
                    )
                )
                st.write(f"**Foutmelding:**\n\n {repr(e)}")

    # Collect feedback
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    st.session_state["feedback_key"] = f"{st.session_state.session_uuid}_{ts}"
    feedback = streamlit_feedback(
        feedback_type="thumbs",
        optional_text_label="(Optioneel) Geef toelichting.",
        max_text_length=None,
        disable_with_score=None,
        args=(),
        kwargs={},
        align="flex-end",
        key=st.session_state["feedback_key"],
    )

st.session_state["feedback_key_search"] = None
