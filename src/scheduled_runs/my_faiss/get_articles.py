import datetime
import os

import requests
from langchain.docstore.document import Document
from pydantic import BaseModel
from unidecode import unidecode

from scheduled_runs.runlogging import logger

HELPJUICE_API_KEY = os.environ["HELPJUICE_API_KEY"]
HELPJUICE_API_URL = os.environ["HELPJUICE_API_URL"]


class Article(BaseModel):
    """Validate the data inside the response using Pydantic."""

    id: int
    name: str
    updated_at: datetime.datetime
    published: bool
    answer: dict[str, str]
    url: str
    body: str = None
    html: str = None

    def model_post_init(self, ctx):
        """This runs automatically when you instantiate an object."""
        self.body = unidecode(self.answer["body_txt"])
        self.html = self.answer["body"]


def get_all_articles() -> list[Document]:
    """Gebruik de Helpjuice API om alle artikelen eruit te trekken.

    Maak er Langchain document objecten van.
    """
    categories = _get_categories()
    query_params = {
        "api_key": HELPJUICE_API_KEY,
        "limit": 1000,  # adjust as needed, this is the maximum value allowed by HelpJuice
        "page": 1,
        "filter[is_published]": True,
    }
    response = requests.get(HELPJUICE_API_URL + "/articles", params=query_params, timeout=3600)
    response.raise_for_status()
    articles = response.json()["articles"]

    # retrieve total nr of pages and then get the articles on other pages:
    total_pages = response.json()["meta"]["total_pages"]
    for page in range(2, total_pages + 1):
        query_params["page"] = page
        response = requests.get(HELPJUICE_API_URL + "/articles", params=query_params, timeout=3600)
        response.raise_for_status()
        next_page_articles = response.json()["articles"]
        articles.extend(next_page_articles)

    logger.info(f"Number of articles retrieved from API: {len(articles)}, total pages: {total_pages}")

    docs = []
    for a in articles:
        if "category" in a.keys():  # anders categorieloos, negeren
            if a["category"]["id"] in categories:
                article_parsed = Article(**a)
                pub_date = article_parsed.updated_at.strftime("%Y-%m-%d %H:%M")
                doc = Document(
                    page_content=article_parsed.body,
                    metadata={
                        "source": article_parsed.name,
                        "date": pub_date,
                        "url": article_parsed.url,
                        "id": article_parsed.id,
                    },
                )
                docs.append(doc)

    return docs


def _get_categories():
    """Vind de categorieen waarbij 'Klantenservice (INTERN)' de hoofdmap/hoofdcategorie is (dus hoger in de
    hierarchy)."""
    query_params = {"api_key": HELPJUICE_API_KEY, "limit": 1000}
    response = requests.get(HELPJUICE_API_URL + "/categories", params=query_params, timeout=3600)
    response.raise_for_status()
    categories = response.json()["categories"]
    cat_ids = []
    for c in categories:
        if len(c["hierarchy"]) > 0:  # else: categorie is "VvE TEAM (INTERN)"
            if c["hierarchy"][0]["id"] == 89077:  # als de hoofdmap "Klantenservice (INTERN)" is
                cat_ids.append(c["id"])
    logger.info(f"Number of categories: {len(cat_ids)}")
    return cat_ids


if __name__ == "__main__":
    get_all_articles()
