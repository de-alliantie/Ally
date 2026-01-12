from datetime import datetime

import unidecode
from bs4 import BeautifulSoup
from langchain.docstore.document import Document


def prepare_html_docs(big_html: str) -> list[Document]:
    """Prepare HTML documentation from source files."""
    soup = BeautifulSoup(big_html, features="html.parser")
    brs = soup.find_all("br")
    brs = set([str(b) for b in brs])

    articles = soup.find_all("article", class_="question")

    docs = []
    for article in articles:
        # Extract header name
        title = article.find("h1", class_="article-name")
        title = title.text.strip()
        title = title.replace("\n", "")

        # Extract author info
        author_info = article.find("div", class_="author-info")
        if author_info is not None:
            author_info = author_info.p.text.strip()
            pub_date = author_info.split("Last published at: ")[1]
            pub_date = datetime.strptime(pub_date, "%B %d, %Y")
            pub_date = pub_date.strftime("%Y-%m-%d")
            author = author_info.split("Written by ")[1].split(" |")[0]
        else:
            pub_date = None
            author = None

        # Extract article body text
        article_body = article.find("div", class_="body")
        article_body_str = str(article_body)
        for br in brs:
            article_body_str = article_body_str.replace(br, "\n")
        article_body_str = unidecode.unidecode(article_body_str)
        article_body = BeautifulSoup(article_body_str, "html.parser").getText().strip()

        # Get URL out of html article
        url_tag = article.find("meta", {"name": "codename"})
        if url_tag:
            url = url_tag["content"]
        else:
            url = ""

        article_id = article.find("meta", {"name": "id"})["content"]

        # Create document object
        doc = Document(
            page_content=article_body,
            metadata={"source": title, "date": pub_date, "author": author, "url_end": url, "id": article_id},
        )
        docs.append(doc)
    return docs


if __name__ == "__main__":
    with open("data/source-documents/de-alliantie-questions.html", "r") as file:
        html_str = file.read()
    docs = prepare_html_docs(html_str)
