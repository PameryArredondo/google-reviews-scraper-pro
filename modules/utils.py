"""
Utility functions for Google Maps Reviews Scraper.
"""
import json
import logging
import re
import time
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from typing import List, Dict, Any

from selenium.common.exceptions import (NoSuchElementException,
                                        StaleElementReferenceException,
                                        TimeoutException)
from selenium.webdriver import Chrome
from selenium.webdriver.common.by import By
from selenium.webdriver.remote.webelement import WebElement
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

# Logger
log = logging.getLogger("scraper")

# Constants for language detection
HEB_CHARS = re.compile(r"[\u0590-\u05FF]")
THAI_CHARS = re.compile(r"[\u0E00-\u0E7F]")


@lru_cache(maxsize=1024)
def detect_lang(txt: str) -> str:
    """Detect language based on character sets"""
    if HEB_CHARS.search(txt):  return "he"
    if THAI_CHARS.search(txt): return "th"
    return "en"


@lru_cache(maxsize=128)
def safe_int(s: str | None) -> int:
    """Safely convert string to integer, returning 0 if not possible"""
    m = re.search(r"\d+", s or "")
    return int(m.group()) if m else 0


def try_find(el: WebElement, css: str, *, all=False) -> List[WebElement]:
    """Safely find elements by CSS selector without raising exceptions"""
    try:
        if all:
            return el.find_elements(By.CSS_SELECTOR, css)
        obj = el.find_element(By.CSS_SELECTOR, css)
        return [obj] if obj else []
    except (NoSuchElementException, StaleElementReferenceException):
        return []


def first_text(el: WebElement, css: str) -> str:
    """Get text from the first matching element that has non-empty text"""
    for e in try_find(el, css, all=True):
        try:
            if (t := e.text.strip()):
                return t
        except StaleElementReferenceException:
            continue
    return ""


_UNIT_KEYWORDS = {
    "year": [
        "year", "years",
        "tahun",
        "año", "años",
        "an", "ans", "année", "années",
        "jahr", "jahre", "jahren",
        "anno", "anni",
        "ano", "anos",
        "год", "года", "лет",
        "년",
        "年",
        "سنة", "سنوات",
        "साल", "वर्ष",
        "yıl",
        "jaar", "jaren",
        "rok", "lat", "lata", "roku",
        "năm",
        "år",
        "vuosi", "vuotta",
        "χρόνο", "χρόνια", "έτος", "έτη",
        "roky", "let", "lety",
        "ani",
        "év", "éve", "évet",
        "ปี",
        "שנה", "שנים",
        "година", "години",
    ],
    "month": [
        "month", "months",
        "bulan",
        "mes", "meses",
        "mois",
        "monat", "monate", "monaten",
        "mese", "mesi",
        "mês",
        "месяц", "месяца", "месяцев",
        "개월",
        "か月", "ヶ月", "ケ月", "个月", "個月",
        "شهر", "أشهر", "شهور",
        "महीना", "महीने",
        "ay",
        "maand", "maanden",
        "miesiąc", "miesiące", "miesięcy",
        "tháng",
        "månad", "månader",
        "måned", "måneder",
        "kuukausi", "kuukautta",
        "μήνα", "μήνες",
        "měsíc", "měsíce", "měsíců", "měsíci",
        "lună", "luni",
        "hónap", "hónapja",
        "เดือน",
        "חודש", "חודשים",
        "месец", "месеца",
    ],
    "week": [
        "week", "weeks",
        "minggu",
        "semana", "semanas",
        "semaine", "semaines",
        "woche", "wochen",
        "settimana", "settimane",
        "неделя", "недели", "недель",
        "주",
        "週間", "週",
        "周",
        "أسبوع", "أسابيع",
        "हफ्ता", "हफ्ते", "सप्ताह",
        "hafta",
        "weken",
        "tydzień", "tygodnie", "tygodni",
        "tuần",
        "vecka", "veckor",
        "uke", "uker",
        "uge", "uger",
        "viikko", "viikkoa",
        "εβδομάδα", "εβδομάδες",
        "týden", "týdny", "týdnů",
        "săptămână", "săptămâni",
        "hét", "hete",
        "สัปดาห์",
        "שבוע", "שבועות",
        "седмица", "седмици",
    ],
    "day": [
        "day", "days",
        "hari",
        "día", "días",
        "jour", "jours",
        "tag", "tage", "tagen",
        "giorno", "giorni",
        "dia", "dias",
        "день", "дня", "дней",
        "일",
        "日",
        "يوم", "أيام",
        "दिन",
        "gün",
        "dag", "dagen", "dagar",
        "dzień", "dni",
        "ngày",
        "päivä", "päivää",
        "ημέρα", "ημέρες", "μέρα", "μέρες",
        "den", "dny", "dnů", "dní",
        "zi", "zile",
        "nap", "napja",
        "วัน",
        "יום", "ימים",
        "ден", "дни",
    ],
    "hour": [
        "hour", "hours",
        "jam",
        "hora", "horas",
        "heure", "heures",
        "stunde", "stunden",
        "ora", "ore",
        "час", "часа", "часов",
        "시간",
        "時間",
        "小时", "小時",
        "ساعة", "ساعات",
        "घंटा", "घंटे",
        "saat",
        "uur",
        "godzina", "godziny", "godzin",
        "giờ",
        "timme", "timmar",
        "time", "timer",
        "tunti", "tuntia",
        "ώρα", "ώρες",
        "hodina", "hodiny", "hodin",
        "óra", "órája",
        "ชั่วโมง",
        "שעה", "שעות",
    ],
    "minute": [
        "minute", "minutes",
        "menit",
        "minuto", "minutos",
        "minuten",
        "minuti",
        "минута", "минуты", "минут", "минути",
        "분",
        "分",
        "دقيقة", "دقائق",
        "मिनट",
        "dakika",
        "minuta", "minuty", "minut",
        "phút",
        "minuter",
        "minutt", "minutter",
        "minuutti", "minuuttia",
        "λεπτό", "λεπτά",
        "perc", "perce",
        "นาที",
        "דקה", "דקות",
    ],
}

# Dual forms (Arabic/Hebrew) where the word itself encodes "2"
_DUAL_FORMS = {
    "שנתיים": ("year", 2), "חודשיים": ("month", 2), "שבועיים": ("week", 2),
    "יומיים": ("day", 2), "שעתיים": ("hour", 2),
    "سنتين": ("year", 2), "شهرين": ("month", 2), "أسبوعين": ("week", 2),
    "يومين": ("day", 2), "ساعتين": ("hour", 2),
}

# Build reverse lookup: keyword → unit (sorted longest-first for matching priority)
_WORD_TO_UNIT = {}
for _unit, _keywords in _UNIT_KEYWORDS.items():
    for _kw in _keywords:
        _WORD_TO_UNIT[_kw.lower()] = _unit
_SORTED_KEYWORDS = sorted(_WORD_TO_UNIT.items(), key=lambda x: -len(x[0]))


def parse_date_to_iso(date_str: str) -> str:
    """
    Parse relative date strings in 25+ languages into ISO format.
    Used as a fallback when exact timestamp is not available from the API.
    """
    if not date_str:
        return ""

    try:
        now = datetime.now(timezone.utc).replace(microsecond=0)
        text = date_str.lower()

        # Check dual forms first (Arabic/Hebrew "two years" as single word)
        for dual_word, (unit, amount) in _DUAL_FORMS.items():
            if dual_word in text:
                return _compute_date(now, unit, amount)

        # Extract numeric value (default 1 for "a year ago", "setahun lalu", etc.)
        num_match = re.search(r'\d+', text)
        amount = int(num_match.group()) if num_match else 1

        # Find time unit keyword in any language
        for kw, unit in _SORTED_KEYWORDS:
            if kw in text:
                return _compute_date(now, unit, amount)

        return ""
    except Exception:
        return ""


def _compute_date(now: datetime, unit: str, amount: int) -> str:
    """Subtract the given amount of time units from now and return ISO string."""
    deltas = {
        "minute": timedelta(minutes=amount),
        "hour":   timedelta(hours=amount),
        "day":    timedelta(days=amount),
        "week":   timedelta(weeks=amount),
        "month":  timedelta(days=30 * amount),
        "year":   timedelta(days=365 * amount),
    }
    dt = now - deltas.get(unit, timedelta())
    return dt.isoformat()


# ---------------------------------------------------------------------------
# Exact timestamp extraction via CDP network interception
# ---------------------------------------------------------------------------

def _parse_listugcposts(response_text: str) -> Dict[str, str]:
    """
    Parse a raw listugcposts API response and return a dict mapping
    review_id -> exact ISO date string (YYYY-MM-DD).

    The response is a XSSI-protected JSON array:
      parsed[2] = list of reviews
      each review: r[0][1][2] = microsecond timestamp (16-digit int)
                   r[0][0]    = review ID string (matches data-review-id in DOM)
    """
    result: Dict[str, str] = {}
    try:
        clean = response_text.lstrip(")]}'\n")
        parsed = json.loads(clean)
        reviews = parsed[2] if len(parsed) > 2 else None
        if not reviews:
            return result
        for r in reviews:
            try:
                inner = r[0]
                if not inner:
                    continue
                review_id = inner[0]          # data-review-id value
                place_data = inner[1]
                if not place_data or not review_id:
                    continue
                ts_us = place_data[2]         # microseconds since epoch
                if ts_us:
                    dt = datetime.fromtimestamp(ts_us / 1_000_000, tz=timezone.utc)
                    result[review_id] = dt.date().isoformat()
            except Exception as e:
                log.debug(f"Error parsing individual review in listugcposts: {e}")
    except Exception as e:
        log.debug(f"Error parsing listugcposts response: {e}")
    return result


def attach_timestamp_interceptor(driver: Chrome) -> Dict[str, str]:
    """
    Attach a CDP Network listener to the driver that captures exact review
    dates from Google Maps' listugcposts API responses.

    Call this ONCE immediately after setup_driver(), before any navigation.

    Returns a shared dict that is populated in-place as reviews load.
    The dict maps review_id (str) -> ISO date string (str, e.g. "2026-03-06").
    Pass this dict into RawReview.from_card() or the scrape loop to look up
    exact dates by review ID instead of parsing relative strings.

    Usage:
        driver = self.setup_driver(headless)
        ts_cache = attach_timestamp_interceptor(driver)
        # ... navigate, scroll reviews ...
        # ts_cache is now populated with review_id -> date entries
        exact_date = ts_cache.get(review_id)  # "2026-03-06" or None
    """
    ts_cache: Dict[str, str] = {}

    try:
        driver.execute_cdp_cmd("Network.enable", {})

        def on_response(event: Dict[str, Any]) -> None:
            url = event.get("response", {}).get("url", "")
            if "listugcposts" not in url:
                return
            request_id = event.get("requestId")
            if not request_id:
                return
            try:
                body = driver.execute_cdp_cmd(
                    "Network.getResponseBody", {"requestId": request_id}
                )
                text = body.get("body", "")
                if not text:
                    return
                batch = _parse_listugcposts(text)
                ts_cache.update(batch)
                log.debug(f"listugcposts: captured {len(batch)} timestamps, total {len(ts_cache)}")
            except Exception as e:
                log.debug(f"CDP response capture error: {e}")

        driver.add_cdp_listener("Network.responseReceived", on_response)
        log.info("CDP timestamp interceptor attached")

    except Exception as e:
        log.warning(f"Could not attach CDP timestamp interceptor: {e}. "
                    f"Falling back to relative date parsing.")

    return ts_cache


# ---------------------------------------------------------------------------
# Existing helper utilities (unchanged)
# ---------------------------------------------------------------------------

def first_attr(el: WebElement, css: str, attr: str) -> str:
    """Get attribute value from the first matching element that has a non-empty value"""
    for e in try_find(el, css, all=True):
        try:
            if (v := (e.get_attribute(attr) or "").strip()):
                return v
        except StaleElementReferenceException:
            continue
    return ""


def click_if(driver: Chrome, css: str, delay: float = .25, timeout: float = 5.0) -> bool:
    """
    Click element if it exists and is clickable, with timeout and better error handling.
    """
    try:
        elements = driver.find_elements(By.CSS_SELECTOR, css)
        if not elements:
            return False

        for element in elements:
            try:
                if element.is_displayed() and element.is_enabled():
                    element.click()
                    time.sleep(delay)
                    return True
            except Exception:
                continue

        try:
            WebDriverWait(driver, timeout).until(
                EC.element_to_be_clickable((By.CSS_SELECTOR, css))
            ).click()
            time.sleep(delay)
            return True
        except TimeoutException:
            return False

    except Exception as e:
        log.debug(f"Error in click_if: {str(e)}")
        return False


def get_current_iso_date() -> str:
    """Return current UTC time in ISO format."""
    return datetime.now(timezone.utc).isoformat()
