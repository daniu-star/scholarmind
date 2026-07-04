"""Enum types for the CNKI downloader system."""

from enum import Enum


class TaskStatus(str, Enum):
    PENDING = "pending"
    QUEUED = "queued"
    ASSIGNED = "assigned"
    PROCESSING = "processing"
    DOWNLOADING = "downloading"
    COMPLETED = "completed"
    FAILED = "failed"
    RETRYING = "retrying"
    CANCELLED = "cancelled"


class Discipline(str, Enum):
    NEWS_COMM = "新闻传播学"
    AI = "人工智能"
    ANTHROPOLOGY = "人类学"
    CS = "计算机科学"
    CHEMISTRY = "化学"


class CAPTCHAType(str, Enum):
    SLIDE = "slide"
    CLICK = "click"
    TEXT = "text"
    NONE = "none"


class ErrorCategory(str, Enum):
    NETWORK = "network"
    RATE_LIMIT = "rate_limit"
    CAPTCHA = "captcha"
    PARSE = "parse"
    PDF_UNAVAILABLE = "pdf_unavailable"
    AUTH = "auth"
    UNKNOWN = "unknown"


class WorkerStatus(str, Enum):
    IDLE = "idle"
    WORKING = "working"
    PAUSED = "paused"
    DEAD = "dead"


class PipelineStage(str, Enum):
    JOURNAL_HOMEPAGE = "journal_homepage"
    ISSUE_LIST = "issue_list"
    PAPER_LIST = "paper_list"
    PAPER_DETAIL = "paper_detail"
    PDF_DOWNLOAD = "pdf_download"
