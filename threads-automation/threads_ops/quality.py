"""Pre-publish checks. Deterministic rules first; AI review is optional and only adds issues."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from urllib.parse import urlparse

from .settings import THREADS_TEXT_LIMIT, AccountSettingsModel

URL_RE = re.compile(r"https?://[^\s<>\"'）)]+", re.IGNORECASE)
BARE_DOMAIN_RE = re.compile(r"\b(?:[a-z0-9-]+\.)+(?:com|net|jp|io|co|me|ly|gl|app|dev|info|biz)\b", re.IGNORECASE)

GUARANTEE_PATTERNS = [
    r"必ず(?:稼|儲|成功|結果)", r"絶対(?:に)?(?:稼|儲|成功)", r"確実に(?:稼|儲)", r"誰でも(?:簡単|すぐ|確実)",
    r"(?:元本|収益|収入|利益)(?:を)?保証", r"放置(?:で|するだけで)(?:稼|儲)", r"寝てるだけ", r"100\s*%\s*(?:稼|儲|成功)",
]
TESTIMONIAL_PATTERNS = [
    r"(?:受講生|会員|メンバー|生徒|参加者)の?[A-ZＡ-Ｚ]?さん(?:は|が)",
    r"(?:月|年)(?:収|商)?\s*\d[\d,，.]*\s*(?:万|千|円)",
    r"\d[\d,，.]*\s*万円\s*(?:稼|達成|突破|売り上げ|売上)",
    r"(?:実績|成果)\s*\d",
]
MONEY_NUMBER_RE = re.compile(r"\d[\d,，.]*\s*(?:万|千|億)?\s*(?:円|ドル|%|％)")
BROKEN_PATTERNS = [r"```", r"\bas an ai\b", r"AIとして", r"申し訳(?:ありません|ございません)が", r"\{\{", r"\}\}", r"\bundefined\b", r"\bnull\b"]


@dataclass
class CheckResult:
    passed: bool
    issues: list[dict] = field(default_factory=list)   # {code, message, severity}

    def add(self, code: str, message: str, severity: str = "error") -> None:
        self.issues.append({"code": code, "message": message, "severity": severity})
        if severity == "error":
            self.passed = False

    def as_dict(self) -> dict:
        return {"passed": self.passed, "issues": self.issues}


def normalize_text(t: str) -> str:
    t = unicodedata.normalize("NFKC", t)
    return re.sub(r"\s+", "", t).lower()


def url_domain(url: str) -> str | None:
    try:
        host = urlparse(url).hostname
    except ValueError:
        return None
    return host.lower() if host else None


def ngrams(t: str, n: int = 3) -> set[str]:
    t = normalize_text(t)
    if len(t) < n:
        return {t} if t else set()
    return {t[i : i + n] for i in range(len(t) - n + 1)}


def similarity(a: str, b: str) -> float:
    ga, gb = ngrams(a), ngrams(b)
    if not ga or not gb:
        return 0.0
    return len(ga & gb) / len(ga | gb)


def _approved_text(s: AccountSettingsModel) -> str:
    return normalize_text(" ".join(f.statement for f in s.business.approved_facts))


def rule_check(
    text: str | None,
    s: AccountSettingsModel,
    *,
    recent_texts: list[str],
    recent_themes: list[str],
    recent_ctas: list[str],
    theme: str | None,
    cta_key: str | None,
) -> CheckResult:
    r = CheckResult(passed=True)
    if text is None or not text.strip():
        r.add("empty", "生成結果が空です")
        return r
    stripped = text.strip()
    length = len(stripped)
    if length > THREADS_TEXT_LIMIT:
        r.add("too_long_api", f"Threadsの上限{THREADS_TEXT_LIMIT}文字を超えています（{length}文字）")
    if length > s.content.max_chars:
        r.add("too_long", f"設定上限{s.content.max_chars}文字を超えています（{length}文字）")
    if length < s.content.min_chars:
        r.add("too_short", f"設定下限{s.content.min_chars}文字未満です（{length}文字）")
    for pat in BROKEN_PATTERNS:
        if re.search(pat, stripped, re.IGNORECASE):
            r.add("broken_output", f"生成結果が壊れている可能性があります（{pat}）")
            break
    norm = normalize_text(stripped)
    for phrase in s.content.banned_phrases:
        if phrase and normalize_text(phrase) in norm:
            r.add("banned_phrase", f"禁止表現「{phrase}」を含みます")
    for pat in GUARANTEE_PATTERNS:
        if re.search(pat, stripped):
            r.add("guarantee", "収益や成功を保証する誇大表現を含みます")
            break
    approved = _approved_text(s)
    for pat in TESTIMONIAL_PATTERNS:
        for m in re.finditer(pat, stripped):
            if normalize_text(m.group(0)) not in approved:
                r.add("unverified_claim", f"承認済みの事実にない体験談・実績表現「{m.group(0)}」を含みます")
                break
    for m in MONEY_NUMBER_RE.finditer(stripped):
        if normalize_text(m.group(0)) not in approved:
            r.add("unverified_number", f"承認済みの事実にない金額・割合「{m.group(0)}」を含みます")
            break
    if not s.business.service_name and re.search(r"(?:私の|うちの|当)(?:サロン|講座|コミュニティ)では", stripped):
        r.add("unverified_offer", "商品情報が未設定のため、サロン・講座の具体的な内容は書けません")
    for m in URL_RE.finditer(stripped):
        d = url_domain(m.group(0))
        if d is None or not any(d == a or d.endswith("." + a) for a in s.business.allowed_domains):
            r.add("url_not_allowed", f"許可されていないURL「{m.group(0)}」を含みます")
    for m in BARE_DOMAIN_RE.finditer(URL_RE.sub(" ", stripped)):
        d = m.group(0).lower()
        if not any(d == a or d.endswith("." + a) for a in s.business.allowed_domains):
            r.add("url_not_allowed", f"許可されていないドメイン「{m.group(0)}」を含みます")
    for prev in recent_texts:
        if normalize_text(prev) == norm:
            r.add("duplicate", "過去の投稿と同一の文章です")
            break
        sim = similarity(prev, stripped)
        if sim >= s.checks.similarity_threshold:
            r.add("too_similar", f"過去の投稿と類似しています（類似度{sim:.2f}）")
            break
    n = s.checks.theme_max_consecutive
    if theme and len(recent_themes) >= n and all(t == theme for t in recent_themes[:n]):
        r.add("theme_streak", f"同じテーマ「{theme}」が{n}回連続しています")
    n = s.checks.cta_max_consecutive
    if cta_key and cta_key != "none" and len(recent_ctas) >= n and all(c == cta_key for c in recent_ctas[:n]):
        r.add("cta_streak", f"同じCTAが{n}回連続しています")
    return r
