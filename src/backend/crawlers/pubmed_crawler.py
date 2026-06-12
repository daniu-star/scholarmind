"""PubMed crawler adapter — uses E-utilities API."""

import logging
from datetime import datetime, timedelta
from xml.etree import ElementTree

import aiohttp

from .base import BaseCrawler

logger = logging.getLogger(__name__)


class PubMedCrawler(BaseCrawler):
    """PubMed crawler using the E-utilities API."""

    source_db = "pubmed"
    rate_limit = 0.5

    ESEARCH_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
    EFETCH_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"

    async def _search_ids(self, term: str, count: int = 20) -> list[str]:
        """Search PubMed and return a list of PMIDs."""
        params = {
            "db": "pubmed",
            "term": term,
            "retmax": count,
            "retmode": "json",
            "sort": "relevance",
        }
        async with aiohttp.ClientSession() as session:
            async with session.get(self.ESEARCH_URL, params=params) as resp:
                if resp.status != 200:
                    logger.error(f"[pubmed] esearch returned status {resp.status}")
                    return []
                data = await resp.json()
                return data.get("esearchresult", {}).get("idlist", [])

    async def _fetch_details(self, pmids: list[str]) -> list[dict]:
        """Fetch paper details for a list of PMIDs."""
        if not pmids:
            return []

        params = {
            "db": "pubmed",
            "id": ",".join(pmids),
            "retmode": "xml",
        }
        async with aiohttp.ClientSession() as session:
            async with session.get(self.EFETCH_URL, params=params) as resp:
                if resp.status != 200:
                    logger.error(f"[pubmed] efetch returned status {resp.status}")
                    return []
                xml_text = await resp.text()

        return self._parse_xml(xml_text)

    def _parse_xml(self, xml_text: str) -> list[dict]:
        """Parse PubMed XML response into standard format."""
        results = []
        try:
            root = ElementTree.fromstring(xml_text)
        except ElementTree.ParseError as e:
            logger.error(f"[pubmed] XML parse error: {e}")
            return []

        for article in root.findall(".//PubmedArticle"):
            medline = article.find(".//MedlineCitation")
            if medline is None:
                continue

            article_data = medline.find("Article")
            if article_data is None:
                continue

            # Title
            title_el = article_data.find(".//ArticleTitle")
            title = title_el.text if title_el is not None and title_el.text else ""

            # Authors
            authors_list = []
            for author in article_data.findall(".//Author"):
                last = author.find("LastName")
                fore = author.find("ForeName")
                name = ""
                if fore is not None and fore.text:
                    name += fore.text + " "
                if last is not None and last.text:
                    name += last.text
                if name.strip():
                    authors_list.append(name.strip())
            authors = ", ".join(authors_list)

            # Year
            year = ""
            pub_date = article_data.find(".//PubDate")
            if pub_date is not None:
                year_el = pub_date.find("Year")
                if year_el is not None and year_el.text:
                    year = year_el.text

            # Journal
            journal_el = article_data.find(".//Journal/Title")
            source = journal_el.text if journal_el is not None and journal_el.text else ""

            # Abstract
            abstract_parts = []
            for abs_text in article_data.findall(".//AbstractText"):
                if abs_text.text:
                    label = abs_text.get("Label", "")
                    if label:
                        abstract_parts.append(f"{label}: {abs_text.text}")
                    else:
                        abstract_parts.append(abs_text.text)
            abstract = " ".join(abstract_parts)[:1000]

            # DOI
            doi = ""
            for aid in article.findall(".//ArticleId"):
                if aid.get("IdType") == "doi":
                    doi = aid.text or ""
                    break

            # PMID
            pmid_el = medline.find("PMID")
            pmid = pmid_el.text if pmid_el is not None else ""

            # Keywords
            keywords_list = []
            for kw in medline.findall(".//Keyword"):
                if kw.text:
                    keywords_list.append(kw.text)

            results.append({
                "title": title,
                "authors": authors,
                "year": year,
                "source": source,
                "abstract": abstract,
                "doi": doi,
                "citations": 0,
                "is_core": False,
                "keywords": keywords_list,
                "url": f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/" if pmid else "",
            })

        return results

    async def crawl_hot(self, count: int = 50) -> list[dict]:
        """Crawl hot papers — search for highly cited recent papers."""
        # PubMed doesn't have a direct 'hot' endpoint; use popular terms
        term = "(artificial intelligence OR machine learning OR deep learning) AND 2023:2026[pdat]"
        try:
            pmids = await self.run_with_rate_limit(self._search_ids, term, count)
            raw = await self.run_with_rate_limit(self._fetch_details, pmids)
            return self.normalize_batch(raw)
        except Exception as e:
            logger.error(f"[pubmed] crawl_hot failed: {e}")
            return []

    async def crawl_latest(self, count: int = 100) -> list[dict]:
        """Crawl latest papers from the past 7 days."""
        recent = (datetime.now() - timedelta(days=7)).strftime("%Y/%m/%d")
        today = datetime.now().strftime("%Y/%m/%d")
        term = f"{recent}:{today}[pdat]"
        try:
            pmids = await self.run_with_rate_limit(self._search_ids, term, count)
            raw = await self.run_with_rate_limit(self._fetch_details, pmids)
            return self.normalize_batch(raw)
        except Exception as e:
            logger.error(f"[pubmed] crawl_latest failed: {e}")
            return []

    async def crawl_by_keyword(self, keyword: str, count: int = 20) -> list[dict]:
        """Crawl papers by keyword."""
        try:
            pmids = await self.run_with_rate_limit(self._search_ids, keyword, count)
            raw = await self.run_with_rate_limit(self._fetch_details, pmids)
            return self.normalize_batch(raw)
        except Exception as e:
            logger.error(f"[pubmed] crawl_by_keyword failed for '{keyword}': {e}")
            return []
