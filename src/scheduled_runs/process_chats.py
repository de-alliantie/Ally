import argparse
import copy
import datetime
import json
import os
from pathlib import Path
from typing import List, Optional

import pypandoc
from azure.identity import DefaultAzureCredential
from azure.storage.blob import ContainerClient
from pydantic import BaseModel
from pymsteams import TeamsWebhookException, connectorcard
from sharepoint_utility import SharePointUtility

from scheduled_runs.runlogging import logger

SHAREPOINT_URL = os.environ["SHAREPOINT_URL"]

INPUT_FOLDER = "data/chats_json"
OUTPUT_FOLDER = "data/chats_report/"
DEFAULT_PAYLOAD_TEMPLATE = {
    "type": "message",
    "attachments": [
        {
            "contentType": "application/vnd.microsoft.card.adaptive",
            "content": {
                "type": "AdaptiveCard",
                "body": [],
                "actions": [],
                "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
                "version": "1.0",
                "msteams": {"width": "Full"},
            },
        }
    ],
}


def helper_container_client(credential, environment: str):
    """Initialize container client (datalake, container ds-files)."""
    name_storage = os.environ["DATALAKE_NAME_PRD"] if environment == "prd" else os.environ["DATALAKE_NAME_DEV"]
    return ContainerClient(
        account_url=f"https://{name_storage}.blob.core.windows.net", container_name="ds-files", credential=credential
    )


class ProcessChats:
    """Process chat data and handle chat operations."""

    def __init__(self, credential, date_to_process: str, environment: str = "dev"):
        """Initialize ProcessChats with credentials and environment."""
        self.credential = credential
        self.environment = environment
        self.date_to_process = date_to_process
        self.date_to_process_yyyymmdd = date_to_process.replace("-", "")
        """Initialize ProcessChats."""

        self.input_folder = INPUT_FOLDER
        self.output_folder = OUTPUT_FOLDER
        self.output_md_file = "output_all_conversations.md"
        self.output_docx_file = f"{self.date_to_process_yyyymmdd}_output_all_conversations.docx"
        self.filepath_md_file = f"{self.output_folder}/{self.output_md_file}"
        self.filepath_docx_file = f"{self.output_folder}/{self.output_docx_file}"

        Path(self.input_folder).mkdir(parents=True, exist_ok=True)
        Path(self.output_folder).mkdir(parents=True, exist_ok=True)

    def main(self) -> dict:
        """Main function to process the chats."""
        self.retrieve_chats()
        json_files = self.load_json_files()
        info = {}
        full_conversations = self.find_full_conversations(json_files)
        full_conversations, nr_questions, nr_sessions = self.edit_session_id_and_count(full_conversations)
        info["number_questions"] = nr_questions
        info["number_sessions"] = nr_sessions
        info["number_of_conversations"] = len(full_conversations)
        conversations_md = self.format_to_markdown(full_conversations)
        self.merge_markdown_files(conversations_md)
        self.convert_to_docx()
        info["date_to_process"] = self.date_to_process
        return info

    def retrieve_chats(self):
        """Retrieve chats from datalake."""
        aux = self.environment if self.environment != "dev" else "tst"  # for dev we use chats from tst slot app
        base = f"klantenservice-chatbot-medewerker/{aux}/chat/"
        container_client = helper_container_client(self.credential, self.environment)
        filenames = [
            name for name in container_client.list_blob_names() if f"{base}{self.date_to_process_yyyymmdd}" in name
        ]
        for filename in filenames:
            with open(f"{self.input_folder}/{filename.replace(base, '')}", "wb") as f:
                blob_data = container_client.download_blob(f"{filename}").readall()
                f.write(blob_data)

    def load_json_files(self) -> list[dict]:
        """Load JSON files.

        Returns:
            list: A list of dictionaries, each representing the contents of a JSON file.
        """
        json_files = []
        filenames = os.listdir(self.input_folder)
        # sort filenames on timestamp last question:
        sorted_filenames = sorted(filenames, key=lambda x: x.split("_")[2])
        for filename in sorted_filenames:
            if filename.endswith(".json"):
                with open(os.path.join(self.input_folder, filename), "r") as file:
                    json_files.append(json.load(file))
        return json_files

    @staticmethod
    def find_full_conversations(json_files: list[dict]) -> list[dict]:
        """Na elk bericht wordt het gesprek tot dan toe geupload naar het datalake.

        Vind de volledige gesprekken en filter de onvolledige.
        """

        conversations_in_list = []
        for data in json_files:
            messages = [message["content"] for message in data["conversation"]]
            messages_conc = " ".join(messages)
            conversations_in_list.append(messages_conc)

        to_delete = []
        for i in range(len(conversations_in_list)):
            for j in range(i + 1, len(conversations_in_list)):
                if conversations_in_list[i] in conversations_in_list[j]:
                    to_delete.append(i)
                elif conversations_in_list[j] in conversations_in_list[i]:
                    to_delete.append(j)

        json_files_reduced = [json_files[i] for i in range(len(json_files)) if i not in to_delete]

        return json_files_reduced

    def edit_session_id_and_count(self, json_files: list[dict]) -> tuple[list[dict], int, int]:
        """Vervang de session id met een integer en tel het aantal gestelde vragen en het aantal sessies.

        Wanneer de gebruiker op 'Start nieuwe chat' klikt blijft hij in dezelfde sessie, maar als hij de pagina ververst
        wordt het een nieuwe sessie.
        """

        unique_sessions = []
        for f in json_files:
            if f["session_uuid"] not in unique_sessions:
                unique_sessions.append(f["session_uuid"])
        sessions_mapping = {session: i + 1 for i, session in enumerate(unique_sessions)}
        for x in json_files:
            x["session_uuid"] = sessions_mapping[x["session_uuid"]]

        all_questions = []
        for data in json_files:
            messages = [message["content"] for message in data["conversation"] if message["role"] == "user"]
            all_questions.extend(messages)

        return json_files, len(all_questions), len(unique_sessions)

    def format_to_markdown(self, json_files: list[dict]) -> list[str]:
        """Convert conversations (as json files) to Markdown format as a string, put them in a list and pass it to the
        next function."""
        md_strings = []
        for j, data in enumerate(json_files):
            session_uuid = data["session_uuid"]
            timestamp = datetime.datetime.strptime(data["timestamp_last_chat"], "%Y-%m-%d %H:%M:%S")
            conversation = data["conversation"]

            conversation_md = f"## Sessie {session_uuid}, laatste vraag: {timestamp.strftime('%Y-%m-%d %H:%M:%S')}\n\n"
            for message in conversation:
                conversation_md += f"**{message['role'].capitalize()}**: {message['content']}\n\n"
                source_titles = message.get("source_titles", [])
                urls = message.get("urls", [])
                for i in range(len(source_titles)):
                    hyperlink = f"[{source_titles[i]}]({urls[i]})"
                    conversation_md += f"{i + 1}. {hyperlink}\n"
                conversation_md += "\n"

            md_strings.append(conversation_md)
        return md_strings

    def merge_markdown_files(self, list_of_markdown_strings: list[str]):
        """Merge all the Markdown files in the specified folder."""
        merged_md = ""
        for conversation_md in list_of_markdown_strings:
            merged_md += conversation_md + "\n\n"
        with open(self.filepath_md_file, "w") as file:
            file.write(merged_md)

    def convert_to_docx(self):
        """Convert the Markdown file to a DOCX file."""
        pypandoc.convert_file(self.filepath_md_file, "docx", outputfile=self.filepath_docx_file)


class MessageDTO(BaseModel):
    """Data transfer object for messages."""

    text: str
    title: Optional[str] = None
    mention_users: Optional[List] = None
    link_title: Optional[str] = None
    link_url: Optional[str] = None


class TeamsMessenger:
    """Messenger for sending messages to Teams."""

    def __init__(self, webhook_url: str, messageDTO: MessageDTO):
        """Initialize TeamsMessenger with webhook URL and message DTO."""
        self.messageDTO = messageDTO
        self.my_messenger = connectorcard(hookurl=webhook_url)

    def send_message(self):
        """Send a message to Teams."""
        try:
            # Init with message payload template
            self.my_messenger.payload = copy.deepcopy(DEFAULT_PAYLOAD_TEMPLATE)

            # Add title
            if self.messageDTO.title:
                self.my_messenger.payload["attachments"][0]["content"]["body"].append(
                    {"type": "TextBlock", "size": "Large", "weight": "Bolder", "text": self.messageDTO.title}
                )

            # Add text
            self.my_messenger.payload["attachments"][0]["content"]["body"].append(
                {"type": "TextBlock", "size": "Medium", "text": self.messageDTO.text, "wrap": True}
            )

            # Add mentions
            if self.messageDTO.mention_users:
                mentions_entities = []
                mention_text = ""

                for mention_user in self.messageDTO.mention_users:
                    mentions_entities.append(
                        {
                            "type": "mention",
                            "text": f"<at>{mention_user['name']}</at>",
                            "mentioned": {"id": mention_user["email"], "name": mention_user["name"]},
                        }
                    )

                    mention_text += f"@<at>{mention_user['name']}</at> "
                self.my_messenger.payload["attachments"][0]["content"]["body"].append(
                    {"type": "TextBlock", "text": mention_text}
                )
                self.my_messenger.payload["attachments"][0]["content"]["msteams"]["entities"] = mentions_entities

            # Add link
            if self.messageDTO.link_title and self.messageDTO.link_url:
                self.my_messenger.payload["attachments"][0]["content"]["actions"].append(
                    {"type": "Action.OpenUrl", "title": self.messageDTO.link_title, "url": self.messageDTO.link_url}
                )

            # Send message
            self.my_messenger.send()

        except TeamsWebhookException as e:
            logger.error(f"An error occurred when send Teams message. {e}")

        except Exception as e:
            logger.error(f"An error occurred when process sending Teams message. {e}")


if __name__ == "__main__":

    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--date_to_process_yyyymmdd",
        dest="date_to_process",
        default=datetime.date.today().strftime("%Y-%m-%d"),
        type=str,
    )
    args = parser.parse_args()

    if os.environ["ENVIRONMENT"] == "prd":
        sharepoint_folder_path = "Klantenservice-Ally/Gesprekken"

        mention_users_str = os.environ["KLANTENSERVICE_CHAT_REPORTING_MENTION_USERS"]
        teams_webhook = os.environ["TEAMS_WEBHOOK_DCC_KLANTENSERVICE_ALLY"]

        if "," in mention_users_str:

            mention_users_list = mention_users_str.split(",")

            mention_users = [{"name": email.split("@")[0], "email": email} for email in mention_users_list]
    else:
        sharepoint_folder_path = "Klantenservice-Ally/Test/Gesprekken"
        teams_webhook = os.environ["TEAMS_WEBHOOK_DATASCIENCE_ALGEMEEN"]
        mention_users = None

    # Process chats
    credential = DefaultAzureCredential()
    logger.info("Start processing chats")
    process_chats = ProcessChats(credential, args.date_to_process, os.environ["ENVIRONMENT"])
    info = process_chats.main()

    # Write to Sharepoint
    logger.info("Start writing to Sharepoint")

    sp = SharePointUtility()
    sp.connect(
        sitename="DCC-python",
        sharepoint_url=os.environ["SHAREPOINT_URL"],
        tenant_id=os.environ["TENANT_ID"],
        client_id=os.environ["SPO_APPONLY_CERT_DCC_PYTHON_CLIENT_ID"],
        private_key=os.environ["SPO_APPONLY_CERT_DCC_PYTHON_PRIVATE_KEY"],
        private_key_thumbprint=os.environ["SPO_APPONLY_CERT_DCC_PYTHON_PRIVATE_KEY_THUMBPRINT"],
    )

    DATA_SCIENCE_OPS_DRIVE_ID = sp.get_drive_id_by_name(name="Data Science OPS")

    if DATA_SCIENCE_OPS_DRIVE_ID is not None:

        # Upload a file
        response = sp.upload_file(
            drive_id=DATA_SCIENCE_OPS_DRIVE_ID,
            folder_path=sharepoint_folder_path,
            local_file_path=process_chats.filepath_docx_file,
        )

        url_conversations = response.get("webUrl")

    # Communicate to Teams
    logger.info("Start writing to Teams")

    message = MessageDTO(
        text=f"""Aantal vragen gesteld: {info['number_questions']}. Aantal gesprekken: {info['number_of_conversations']}. Aantal sessies: {info['number_sessions']}.""",  # noqa: E501
        title=f"Rapportage gebruik Ally op {info['date_to_process']}",
        mention_users=mention_users,
        link_title="Bekijk de gestelde vragen en de antwoorden die ik heb gegeven",
        link_url=url_conversations,
    )
    messenger = TeamsMessenger(webhook_url=teams_webhook, messageDTO=message)
    messenger.send_message()
