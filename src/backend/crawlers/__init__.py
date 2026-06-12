"""Crawler module for academic resource collection."""

from .base import BaseCrawler
from .cnki_crawler import CNKICrawler
from .crossref_crawler import CrossRefCrawler
from .pubmed_crawler import PubMedCrawler
from .wanfang_crawler import WanfangCrawler
from .weipu_crawler import WeipuCrawler

CRAWLERS = {
    "cnki": CNKICrawler,
    "crossref": CrossRefCrawler,
    "pubmed": PubMedCrawler,
    "wanfang": WanfangCrawler,
    "weipu": WeipuCrawler,
}

__all__ = [
    "BaseCrawler", "CNKICrawler", "CrossRefCrawler",
    "PubMedCrawler", "WanfangCrawler", "WeipuCrawler", "CRAWLERS",
]
