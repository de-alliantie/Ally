import os
from datetime import datetime
from pathlib import Path

from azure.identity import DefaultAzureCredential
from azure.storage.blob import ContainerClient
from langchain.text_splitter import TokenTextSplitter
from langchain_community.vectorstores import FAISS
from langchain_openai import AzureOpenAIEmbeddings

from scheduled_runs.my_faiss.get_articles import get_all_articles
from scheduled_runs.runlogging import logger

EMBEDDINGS_MODEL = "webapps-text-embedding-ada-002"
OPENAI_API_VERSION = "2024-10-21"
NAME_FOLDER = "klantenservice-chatbot-medewerker"
LOCAL_NAME_SUBFOLDER_FAISS_INDEX = "data/faiss"


class CreateFAISSIndex:
    """Create FAISS index from documents in Azure Data Lake.

    Download html document from dev or prd datalake. Then write the faiss index files to the tst or acc folder in the
    case of datalakedev and to the prd folder in the case of the prd datalake.
    """

    embeddings = AzureOpenAIEmbeddings(
        azure_deployment=EMBEDDINGS_MODEL,
        openai_api_version=OPENAI_API_VERSION,
        api_key=os.environ["OPENAI_API_KEY"],
        azure_endpoint=os.environ["OPENAI_ENDPOINT"],
    )

    def __init__(self, environment: str = "tst"):
        """Initialize CreateFAISSIndex with environment and FAISS DB."""
        self.environment = environment
        self.faiss_db = None

    @classmethod
    def inspect_faiss(cls):
        """Retrieve all docs inside a Faiss database to inspect and debug it.

        Make sure the Faiss files are inside the data/faiss folder.
        """
        index_name = list(Path("data/faiss").iterdir())[0].stem
        faiss_db = FAISS.load_local(folder_path="data/faiss", embeddings=cls.embeddings, index_name=index_name)
        docs = faiss_db.similarity_search(query="", fetch_k=100000, k=100000)
        titles = [d.metadata["source"] for d in docs]
        return docs, titles

    def run_all_steps(self) -> None:
        """Run all steps for generating and saving FAISS index."""
        self._generate_embeddings_and_vectorstore()
        self._save_and_upload_vectorstore()

    def _generate_embeddings_and_vectorstore(self) -> None:
        """Generate embeddings for all documents in local folder."""

        text_splitter = TokenTextSplitter(encoding_name="cl100k_base", chunk_size=700, chunk_overlap=70)
        logger.info("Getting articles from Helpjuice API")
        docs = get_all_articles()
        logger.info(f"Number of docs after filter (to put in vectorstore): {len(docs)}")
        if len(docs) < 100:
            raise Exception("Expected more articles in Helpjuice?")
        doc_chunks = text_splitter.split_documents(docs)
        for doc in doc_chunks:
            doc.page_content = "Titel van artikel: " + doc.metadata["source"] + "\n\n" + doc.page_content
        logger.info("Start generating embeddings and vectorstore.")
        self.faiss_db = FAISS.from_documents(doc_chunks, CreateFAISSIndex.embeddings)
        self.faiss_db.save_local(f"{LOCAL_NAME_SUBFOLDER_FAISS_INDEX}")
        return

    def _save_and_upload_vectorstore(self) -> None:
        """Save vectorstore to local folder and upload to Azure Data Lake."""
        logger.info("Uploading vectorstore.")
        name_storage = os.environ["DATALAKE_NAME_PRD"] if self.environment == "prd" else os.environ["DATALAKE_NAME_DEV"]

        client = ContainerClient(
            account_url=f"https://{name_storage}.blob.core.windows.net",
            container_name="ds-files",
            credential=DefaultAzureCredential(),
        )

        # Get current datetime to version the index
        now = datetime.now()
        version = now.strftime("%Y-%m-%d_%H%M")

        logger.info(f"DELETING FAISS FILES {self.environment}")
        old_index_names = list(client.list_blob_names(name_starts_with=f"{NAME_FOLDER}/{self.environment}/faiss/"))
        for name in old_index_names:
            if name.startswith(f"{NAME_FOLDER}/{self.environment}/faiss/"):
                client.delete_blob(blob=name)

        for name in ["index.faiss", "index.pkl"]:
            name_with_version = f'index_{version}.{name.split(".")[1]}'
            with open(f"{LOCAL_NAME_SUBFOLDER_FAISS_INDEX}/{name}", "rb") as data:
                client.upload_blob(
                    name=f"{NAME_FOLDER}/{self.environment}/faiss-historical/{name_with_version}",
                    data=data,
                    overwrite=True,
                )
            with open(f"{LOCAL_NAME_SUBFOLDER_FAISS_INDEX}/{name}", "rb") as data:
                client.upload_blob(
                    name=f"{NAME_FOLDER}/{self.environment}/faiss/{name_with_version}", data=data, overwrite=True
                )
        logger.info(f"uploading complete, uploaded {name_with_version} to {self.environment}")


if __name__ == "__main__":
    # run this to inspect the faiss index:
    # docs, titles = CreateFAISSIndex.inspect_faiss()

    logger.info("Start generating new FAISS index.")
    fi = CreateFAISSIndex(environment=os.environ["ENVIRONMENT"])
    fi.run_all_steps()
