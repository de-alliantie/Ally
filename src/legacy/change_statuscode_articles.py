"""Een script voor het wijzigen van de accessibility status van artikelen, zodat iedereen die de bronnen ziet in Ally,
toegang heeft als diegene op zo'n bron/link klikt.

Het probleem was dat veel artikelen accessibility statuscode 2 (Private) hadden, en dit moest statuscode 0 (Internal)
worden.
"""
import os

import requests
from dotenv import load_dotenv
from requests.auth import HTTPBasicAuth

load_dotenv()

HELPJUICE_API_KEY = os.environ["HELPJUICE_API_KEY"]
HELPJUICE_API_URL = os.environ["HELPJUICE_API_URL"]


def get_all_articles():
    """Gebruik de Helpjuice API om alle artikelen eruit te trekken.

    Maak er Langchain document objecten van
    """
    categories = _get_categories()
    category_ids = [c["id"] for c in categories]

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

    ks_articles = [a for a in articles if a.get("category", {}).get("id") in category_ids]
    # filter[accessibility]  type: Integer, accepts ( 1 - Public, 0 - Internal, 2 - Private )

    public_articles = [a for a in ks_articles if a["accessibility"] == 1]
    private_articles = [a for a in ks_articles if a["accessibility"] == 2]
    internal_articles = [a for a in ks_articles if a["accessibility"] == 0]

    print(
        f"Number of articles: public - {len(public_articles)}, private - {len(private_articles)}, internal - {len(internal_articles)}"  # noqa: E501
    )
    return private_articles


def change_accessibility_status_category(category: dict):
    """Change the accessibility status of a category."""
    id = category["id"]
    if len(category["hierarchy"]) != 6:
        # print(f"skip {id} - {category['name']} --- hierarchy level {len(category['hierarchy']) + 1}")
        return

    url = f"{HELPJUICE_API_URL}categories/{id}"
    print(f"Updating category {id} - {category['name']} --- hierarchy level {len(category['hierarchy']) + 1}")
    headers = {"Content-Type": "application/json"}
    query_params = {"api_key": HELPJUICE_API_KEY}
    data = {"category": {"accessibility": 0}}
    response = requests.put(url, json=data, headers=headers, params=query_params, timeout=60)
    response.raise_for_status()


def change_accessibility_status_article(article: dict):
    """Change accessibility status from 2 (private) to 0 (internal) for all given articles using Helpjuice API."""
    article_id = article["id"]
    url = f"{HELPJUICE_API_URL}articles/{article_id}"
    headers = {"Content-Type": "application/json"}
    query_params = {"api_key": HELPJUICE_API_KEY}
    data = {"article": {"visibility_id": 0}}
    # group id KS Mededwerkers: 1697
    response = requests.put(url, json=data, headers=headers, params=query_params, timeout=60)
    response.raise_for_status()
    print(f"Updated article {article_id} - {article['name']}: to internal (0)")


def test_user_article_access(article_id: str, user_email: str):
    """Test if a user has access to a specific Helpjuice article.

    Returns True if access is allowed, False otherwise.
    """
    query_params = {
        "api_key": HELPJUICE_API_KEY,
    }
    url = f"{HELPJUICE_API_URL}articles/{article_id}"
    basic = HTTPBasicAuth(user_email, "")
    response = requests.get(
        url,
        auth=basic,
        params=query_params,
    )
    if response.status_code == 200:
        print(f"User {user_email} has access to article {article_id}.")
        return True
    else:
        print(f"User {user_email} does NOT have access to article {article_id}. Status code: {response.status_code}")
        return False


def _get_categories() -> list[dict]:
    """Vind de categorieen waarbij "Klantenservice (INTERN)" de hoofdmap/hoofdcategorie is (dus hoger in de
    hierarchy)."""
    # Get categories
    query_params = {"api_key": HELPJUICE_API_KEY, "limit": 1000}
    response = requests.get(HELPJUICE_API_URL + "/categories", params=query_params, timeout=3600)
    response.raise_for_status()
    categories = response.json()["categories"]
    filtered_categories = []
    for c in categories:
        if len(c["hierarchy"]) > 0:  # else: categorie is "VvE TEAM (INTERN)"
            if c["hierarchy"][0]["id"] == 89077:  # als de hoofdmap "Klantenservice (INTERN)" is
                filtered_categories.append(c)
    print(f"Number of filtered categories: {len(filtered_categories)}")
    return filtered_categories


if __name__ == "__main__":
    private_articles = get_all_articles()
    for article in private_articles:
        change_accessibility_status_article(article)
    pass
