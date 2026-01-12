import json
import logging
import os
import uuid
from datetime import datetime
from pathlib import Path

import pandas as pd
import pymsteams
import streamlit as st
from azure.identity import DefaultAzureCredential
from azure.storage.blob import BlobServiceClient, ContainerClient
from langchain.chains import ConversationalRetrievalChain
from langchain.chains.conversational_retrieval.base import (
    BaseConversationalRetrievalChain,
)
from langchain.memory import ConversationSummaryBufferMemory
from langchain.prompts import PromptTemplate
from langchain_community.vectorstores import FAISS
from langchain_core.messages import BaseMessage
from langchain_openai import AzureChatOpenAI, AzureOpenAIEmbeddings

LOCAL_FOLDER_FAISS = "data/faiss"

EMBEDDINGS_MODEL = "webapps-text-embedding-ada-002"
OPENAI_EMBEDDINGS_API_VERSION = "2023-05-15"

CHAT_MODEL = "gpt-4o"
OPENAI_CHAT_API_VERSION = "2024-08-01-preview"

MAX_TOKEN_LIMIT_BSUMMARY = 4000

ENVIRONMENT = os.environ.get("APP_ENVIRONMENT", "tst")
BUILD_TAG = os.environ.get("APP_BUILD_TAG", "-")
BASE_PATH_STORAGE = f"klantenservice-chatbot-medewerker/{ENVIRONMENT}"
LOG_LEVEL = "DEBUG"


def set_styling():
    """Sets all the styling for the app, including CSS styling and de Alliantie logo in sidebar."""
    st.set_page_config(page_title="Vraag het aan Ally", page_icon="src/webapp/img/alliantie_logo.png")

    st.logo("src/webapp/img/logo_wit.png", size="small")
    with open("src/webapp/styles.css") as css:
        st.markdown(f"<style>{css.read()}</style>", unsafe_allow_html=True)


def chat_llm():
    """Initialize chat LLM."""
    return AzureChatOpenAI(
        deployment_name=CHAT_MODEL,
        azure_endpoint=os.environ["OPENAI_SWEDEN_ENDPOINT"],
        openai_api_key=os.environ["OPENAI_SWEDEN"],
        api_version=OPENAI_CHAT_API_VERSION,
        temperature=0,
        streaming=True,
    )


def embeddings() -> AzureOpenAIEmbeddings:
    """Initialize embeddings."""
    return AzureOpenAIEmbeddings(
        azure_deployment=EMBEDDINGS_MODEL,
        openai_api_version=OPENAI_EMBEDDINGS_API_VERSION,
        azure_endpoint=os.environ["OPENAI_ENDPOINT"],
    )


def container_client() -> ContainerClient:
    """Initialize container client."""

    if ENVIRONMENT == "prd":
        name_storage = os.environ["DATALAKE_NAME_PRD"]
    else:
        name_storage = os.environ["DATALAKE_NAME_DEV"]

    return ContainerClient(
        account_url=f"https://{name_storage}.blob.core.windows.net",
        container_name="ds-files",
        credential=DefaultAzureCredential(),
    )


def vectorindex(embeddings: AzureOpenAIEmbeddings) -> tuple[FAISS, str]:
    """Initialize faiss index."""
    Path("data/faiss").mkdir(parents=True, exist_ok=True)
    client = container_client()

    # List all the available faiss indexes
    blob_list = client.list_blobs(name_starts_with=f"{BASE_PATH_STORAGE}/faiss/index")
    filenames = []
    for blob in blob_list:
        filename = blob["name"].split(f"{BASE_PATH_STORAGE}/faiss/")[1]
        filenames.append(filename)

    # Extract the two most recent files
    index_files = sorted(filenames)[-2:]

    # Extract the version name (expects a filename in this format: index_DATETIME.pkl)
    version_name = index_files[-1].split(".")[0].split("index_")[1]

    for filename in index_files:
        filename_no_extension = filename.split(".")[0]
        filepath = f"{BASE_PATH_STORAGE}/faiss/{filename}"
        with open(f"data/faiss/{filename}", "wb") as f:
            blob_data = client.download_blob(filepath).readall()
            f.write(blob_data)

    return (
        FAISS.load_local(folder_path=LOCAL_FOLDER_FAISS, embeddings=embeddings, index_name=filename_no_extension),
        version_name,
    )


# Helpers for RAG chain


def _prompt_template_combine_docs() -> PromptTemplate:
    """Helper function to set prompt template."""
    template = (
        "Gebruik de volgene informatiebron om de vraag, die je aan het eind vindt, te beantwoorden. "
        "Baseer je antwoord enkel op de bron en voeg er niks aan toe wat je zelf verstandig of logisch lijkt. "
        "Als de bron geen relevante informatie bevat, geef dit dan gewoon aan en laat je antwoord daarbij. "
        "Probeer een beknopt antwoord van maximaal 6 zinnen te geven als dat lukt."
        "\n\nInformatiebron met artikelen:\n\n"
        "{context}\n\n"
        "Vraag: {question}\n\n"
        "Behulpzaam antwoord:"
    )
    return PromptTemplate(input_variables=["context", "question"], template=template)


def get_chat_history_dutch(chat_history: list[BaseMessage]) -> str:
    """Get chat history ."""
    _ROLE_MAP = {"human": "Klant: ", "ai": "Medewerker: "}
    buffer = ""
    for dialogue_turn in chat_history:
        if isinstance(dialogue_turn, BaseMessage):
            role_prefix = _ROLE_MAP.get(dialogue_turn.type, f"{dialogue_turn.type}: ")
            buffer += f"\n{role_prefix}{dialogue_turn.content}"
        elif isinstance(dialogue_turn, tuple):
            human = "Klant: " + dialogue_turn[0]
            ai = "Medewerker: " + dialogue_turn[1]
            buffer += "\n" + "\n".join([human, ai])
        else:
            raise ValueError(
                f"Unsupported chat history format: {type(dialogue_turn)}." f" Full chat history: {chat_history} "
            )
    return buffer


def chain_rag(llm: AzureChatOpenAI, vectorindex: FAISS, k: int) -> BaseConversationalRetrievalChain:
    """Initialize RAG chain with memory and summarization."""
    memory = ConversationSummaryBufferMemory(
        memory_key="chat_history",
        return_messages=True,
        llm=llm,
        output_key="answer",
        max_token_limit=MAX_TOKEN_LIMIT_BSUMMARY,
    )
    retriever = vectorindex.as_retriever(search_kwargs={"k": k})
    return ConversationalRetrievalChain.from_llm(
        llm=llm,
        retriever=retriever,  # compression_retriever
        condense_question_prompt=PromptTemplate(
            input_variables=["chat_history", "question"],
            template=(
                "Jij bent een assistent die praat met een medewerker van de klantenservice van de Alliantie. "
                "De Alliantie is een woningcorporatie. Gegeven het volgende gesprek en de vervolgvraag van de klant, herformuleer dit "  # noqa: E501
                "als een op zichzelf staande vraag.\n\nChatgeschiedenis:\n{chat_history}\n\n"
                "Vervolgvraag: {question}\n\nHergeformuleerde vraag:"
            ),
        ),
        combine_docs_chain_kwargs={"prompt": _prompt_template_combine_docs()},
        memory=memory,
        return_source_documents=True,
        get_chat_history=get_chat_history_dutch,
    )


# Helpers for logging


def create_logger(name: str = "KS-FAQ"):
    """Create logger."""
    logger = logging.getLogger(name)
    logger.propagate = False
    logger.setLevel(LOG_LEVEL)
    if sum([isinstance(handler, logging.StreamHandler) for handler in logger.handlers]) == 0:
        ch = logging.StreamHandler()
        ch.setFormatter(logging.Formatter("%(asctime)s.%(msecs)03d-%(name)s-%(levelname)s>>>%(message)s", "%H:%M:%S"))
        logger.addHandler(ch)
    return logger


class FailSavingChat(Exception):
    """Raised when there is a failure in saving & writing chat to the datalake."""

    def __init__(self, message: str, source_document=None):
        """Initialize FailSavingChat exception."""
        self.message = message
        self.source_document = source_document
        super().__init__(self.message)


# Helpers for init of ap


@st.cache_resource(ttl="4h")
def init_llm() -> AzureChatOpenAI:
    """Initialize chat LLM."""
    st.session_state["logger"].debug("Initializing chat LLM in chat-app.")
    return chat_llm()


@st.cache_resource(ttl="4h")
def init_embeddings() -> AzureOpenAIEmbeddings:
    """Initialize embeddings."""
    st.session_state["logger"].debug("Initializing embeddings in chat-app.")
    return embeddings()


@st.cache_resource(ttl="24h")  # to be adjusted when we build automated update of FAISS index
def init_faiss() -> FAISS:
    """Initialize faiss index."""
    st.session_state["logger"].debug("Initializing FAISS in chat-app.")
    return vectorindex(st.session_state["embeddings"])


@st.cache_resource(ttl="4h")
def init_blob_client() -> ContainerClient:
    """Initialize blob client."""
    st.session_state["logger"].debug("Initializing blob client (in chat-app).")
    return container_client()


def init_app():
    """Initialize app."""

    if "session_uuid" not in st.session_state:
        st.session_state["session_uuid"] = f"""{datetime.now().strftime("%Y%m%d%H%M%S")}_{str(uuid.uuid4())}"""
    if "logger" not in st.session_state:
        st.session_state["logger"] = create_logger()
    if "llm" not in st.session_state:
        st.session_state["llm"] = init_llm()
    if "embeddings" not in st.session_state:
        st.session_state["embeddings"] = init_embeddings()
    if "vectorstore" not in st.session_state:
        st.session_state["vectorstore"], st.session_state["faiss_version"] = init_faiss()
    if "blob_client" not in st.session_state:
        st.session_state["blob_client"] = init_blob_client()


# Helpers for feedback & reporting


def blob_name_to_datetime(blob_name: str) -> datetime:
    """Extracts the datetime from blob name.

    Args: blob_name (str): The name of the blob, expected to contain a timestamp in the format YYYYMMDDHHMMSS

    example: '20251113115003_4575337f-2fba-4d3e-8b68-408f56c8e5e2_115105.json'.
    """
    timestamp_str = blob_name.split("/")[-1].split("_")[0]
    return datetime.strptime(timestamp_str, "%Y%m%d%H%M%S")


def retrieve_usage_statistics(starting_from: datetime | None):
    """Reads the production usage statistics JSONs from the datalake and returns a DataFrame.

    If starting_from is provided, only blobs with a timestamp after starting_from, and before today, are included.
    """

    # Initialize a list to store the data
    data = []

    OTAP = "prd"
    DATALAKE_LOGGING_BASE_PATH = f"klantenservice-chatbot-medewerker/{OTAP}/chat/"
    ACCOUNT_NAME = os.environ["DATALAKE_NAME_PRD"]

    # List all blobs in the specified folder
    container_name = "ds-files"
    blob_service_client = BlobServiceClient(
        f"https://{ACCOUNT_NAME}.blob.core.windows.net", credential=DefaultAzureCredential(logging_enable=False)
    )
    container_client = blob_service_client.get_container_client(container_name)
    blob_list = container_client.list_blobs(name_starts_with=DATALAKE_LOGGING_BASE_PATH)
    for i, blob in enumerate(blob_list):
        if blob.name.endswith(".json"):
            blob_datetime = blob_name_to_datetime(blob.name)

            if starting_from is not None:

                # Check if the blob's datetime is after the starting_from date and excludes today.
                if (blob_datetime.date() >= starting_from.date()) and (blob_datetime.date() < datetime.now().date()):
                    st.session_state["logger"].info(f"Trying to download blob {i}: {blob.name}...")
                    blob_client = container_client.get_blob_client(blob.name)
                    blob_data = blob_client.download_blob().readall()
                else:
                    continue

            else:
                if blob_datetime.date() < datetime.now().date():
                    st.session_state["logger"].info(f"Trying to download blob {i}: {blob.name}...")
                    blob_client = container_client.get_blob_client(blob.name)
                    blob_data = blob_client.download_blob().readall()
                else:
                    continue
            try:
                json_data = json.loads(blob_data)
                row = {
                    "environment": json_data.get("environment", None),
                    "session_uuid": json_data.get("session_uuid", None),
                    "timestamp_last_chat": json_data.get("timestamp_last_chat", None),
                    "hashed_user": json_data.get("hashed_user", None),
                }
                data.append(row)
            except Exception as e:
                st.session_state["logger"].warning(f"Failed to process blob {blob.name}: {e}")

    # Create a DataFrame from the data
    df = pd.DataFrame(data)

    if starting_from is not None:
        return df

    # Calculate statistics
    num_rows = len(df)
    num_unique_sessions = df["session_uuid"].nunique() if "session_uuid" in df.columns else 0
    num_unique_users = df["hashed_user"].nunique() if "hashed_user" in df.columns else 0

    print(f"Total questions asked: {num_rows}")
    print(f"Unique session_uuid's: {num_unique_sessions}")
    print(f"Unique hashed_user's: {num_unique_users}")

    # Save the DataFrame as a Parquet file
    df.to_parquet(
        f"data/usage_statistics/{pd.Timestamp.now().strftime('%Y%m%d_%H%M%S')}_usage_statistics.parquet", index=False
    )

    return df


def update_usage_statistics():
    """Updates the usage_statistics file."""

    if os.path.exists("data/usage_statistics"):
        files = [
            f for f in os.listdir("data/usage_statistics/") if os.path.isfile(os.path.join("data/usage_statistics/", f))
        ]
        if len(files) >= 1:
            print("Existing usage statistics found, updating with new data...")
            for file in files:
                date_last_update = datetime.strptime(file.split("_")[0], "%Y%m%d")

                print("Retrieving usage statistics newer than ", date_last_update)

                # Extract usage statistics that are newer than date_last_update
                df_new = retrieve_usage_statistics(starting_from=date_last_update)
                print("Retrieved ", len(df_new), " new records.")

                # Get the old usage statistics
                df_old = pd.read_parquet(f"data/usage_statistics/{file}")

                # Merge old and new statistics
                df_merged = pd.concat([df_old, df_new], ignore_index=True)

                print("Saving updated usage statistics with ", len(df_merged), " total records.")
                df_merged.to_parquet(
                    f"data/usage_statistics/{pd.Timestamp.now().strftime('%Y%m%d_%H%M%S')}_usage_statistics.parquet"
                )

                # Remove the old file
                os.remove(f"data/usage_statistics/{file}")
        else:
            # Case when a folder is present but there is no statistics file in it.
            print("No existing usage statistics found, retrieving all usage statistics up to this point...")
            _ = retrieve_usage_statistics(starting_from=None)
    else:
        # Case when no folder is present
        print("No existing usage statistics found, retrieving all usage statistics up to this point...")
        os.makedirs("data/usage_statistics", exist_ok=False)
        _ = retrieve_usage_statistics(starting_from=None)


def log_result_to_MS_teams(result: str, otap: str) -> None:
    """Logt een string naar een bepaald Microsoft Teams-kanaal.

    Args:
        result (str): Te loggen informatie
        otap (str): Bepaalt of de feedback naar het `Ally Feedback` kanaal of ons OPS kanaal gaat.
    Returns:
        None
    """
    if otap == "prd":
        teams_webhook = os.getenv(
            "TEAMS_WEBHOOK_CHATBOT_ALLY_FEEDBACK"
        )  # dev keyvault is populated with OPS OTA webhook
    else:
        teams_webhook = os.getenv("TEAMS_WEBHOOK_DATASCIENCE_ALGEMEEN")

    myTeamsMessage = pymsteams.connectorcard(teams_webhook)
    result = result.replace("\n", "\n\n")  # a single \n doesn't work
    myTeamsMessage.text(result)
    myTeamsMessage.send()

    return None


def process_feedback(client: BlobServiceClient, user_feedback: dict, type_feedback: str):
    """Process feedback."""
    Path(f"data/feedback/{type_feedback}").mkdir(parents=True, exist_ok=True)
    filename = f"{user_feedback['session_uuid']}-{user_feedback['timestamp_feedback']}.json"
    filepath = f"data/feedback/{type_feedback}/{filename}"
    with open(filepath, "w") as feedbackfile:
        json.dump(user_feedback, feedbackfile)
    with open(filepath, "rb") as feedbackfile:
        client.upload_blob(name=f"{BASE_PATH_STORAGE}/feedback/{type_feedback}/{filename}", data=feedbackfile.read())


def save_chat(client: BlobServiceClient, chat: dict):
    """Save chat."""
    Path("data/chats_json").mkdir(parents=True, exist_ok=True)
    timestamp_no_date = chat["timestamp_last_chat"][11:].replace(":", "")
    filename = f"{chat['session_uuid']}_{timestamp_no_date}.json"
    filepath = f"data/chats_json/{filename}"
    with open(filepath, "w") as chatfile:
        json.dump(chat, chatfile)
    with open(filepath, "rb") as chatfile:
        client.upload_blob(name=f"{BASE_PATH_STORAGE}/chat/{filename}", data=chatfile.read())
