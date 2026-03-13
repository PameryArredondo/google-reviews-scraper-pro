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
from zoneinfo import ZoneInfo


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
_EASTERN = ZoneInfo("America/New_York")

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
        now = datetime.now(_EASTERN).replace(microsecond=0)
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
    return dt.astimezone(_EASTERN).date().isoformat()


# ---------------------------------------------------------------------------
# Exact timestamp + full review data extraction via CDP network interception
# ---------------------------------------------------------------------------

def _parse_listugcposts(response_text: str) -> Dict[str, Any]:
    """
    Parse a raw listugcposts API response and return a dict mapping
    review_id -> dict with all available fields.

    Confirmed structure (from browser debug):
      parsed[2]             = list of review entries
      each entry:
        r[0]                = review object
        r[0][0]             = review ID string (matches data-review-id in DOM)
        r[0][1][2]          = review timestamp (microseconds since epoch)
        r[0][2][0][0]       = star rating (int)
        r[0][2][15][0][0]   = review text
        r[0][3]             = owner reply block (may be None)
        r[0][3][1]          = owner reply timestamp (microseconds since epoch)
        r[0][3][6-18][0][0] = owner reply text (index varies)
    """
    result: Dict[str, Any] = {}
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
                review_id = inner[0]
                if not review_id:
                    continue

                # Review timestamp
                review_date = ""
                try:
                    ts_us = inner[1][2]
                    if ts_us:
                        dt = datetime.fromtimestamp(ts_us / 1_000_000, tz=_EASTERN)
                        review_date = dt.date().isoformat()
                except (TypeError, IndexError):
                    pass

                # Rating
                rating = None
                try:
                    rating = inner[2][0][0]
                except (TypeError, IndexError):
                    pass

                # Review text
                review_text = ""
                try:
                    review_text = inner[2][15][0][0] or ""
                except (TypeError, IndexError):
                    pass

                # Owner reply block
                owner_reply_text = ""
                owner_reply_date = ""
                try:
                    reply_block = inner[3]
                    if reply_block:
                        # Owner reply date: rb[1] (microseconds)
                        try:
                            ots = reply_block[1]
                            if ots:
                                od = datetime.fromtimestamp(ots / 1_000_000, tz=_EASTERN)
                                owner_reply_date = od.date().isoformat()
                        except (TypeError, IndexError):
                            pass
                        # Owner reply text: scan indices 6-18 for first non-empty string
                        for i in range(6, 19):
                            try:
                                val = reply_block[i][0][0]
                                if val and isinstance(val, str) and len(val) > 2:
                                    owner_reply_text = val
                                    break
                            except (TypeError, IndexError):
                                continue
                except (TypeError, IndexError):
                    pass

                result[review_id] = {
                    "review_date":      review_date,
                    "rating":           rating,
                    "review_text":      review_text,
                    "owner_reply_text": owner_reply_text,
                    "owner_reply_date": owner_reply_date,
                }

            except Exception as e:
                log.debug(f"Error parsing individual review in listugcposts: {e}")
    except Exception as e:
        log.debug(f"Error parsing listugcposts response: {e}")
    return result


def attach_timestamp_interceptor(driver: Chrome) -> Dict[str, Any]:
    """
    Inject a JS XHR interceptor via CDP that captures all review fields
    from listugcposts into window._reviewData as a combined object per review ID.
    Compatible with SeleniumBase UC Mode.

    Call this ONCE immediately after setup_driver(), before any navigation.
    Returns a shared dict that poll_timestamp_responses() will populate.

    Confirmed structure (from browser debug):
      r[0]                = review object
      r[0][0]             = review ID
      r[0][1][2]          = review timestamp (microseconds)
      r[0][2][0][0]       = star rating
      r[0][2][15][0][0]   = review text
      r[0][3]             = owner reply block (may be null)
      r[0][3][1]          = owner reply timestamp (microseconds)
      r[0][3][6-18][0][0] = owner reply text (index varies by review)
    """
    ts_cache: Dict[str, Any] = {}
    try:
        driver.execute_cdp_cmd('Page.addScriptToEvaluateOnNewDocument', {
            'source': '''
                window._reviewData = {};
                window._ownerDebug = {};

                const _origOpen = XMLHttpRequest.prototype.open;
                XMLHttpRequest.prototype.open = function(method, url) {
                    this._url = url;
                    this.addEventListener('load', function() {
                        if (!this._url || !this._url.includes('listugcposts')) return;
                        try {
                            const clean   = this.responseText.replace(/^\\)\\]\\}'\\n/, '');
                            const parsed  = JSON.parse(clean);
                            const reviews = parsed[2];
                            if (!reviews) return;

                            reviews.forEach(r => {
                                try {
                                    const inner = r[0];
                                    if (!inner) return;
                                    const rid = inner[0];
                                    if (!rid) return;

                                    // Review timestamp: r[0][1][2] (microseconds)
                                    let reviewDate = null;
                                    try {
                                        const ts = inner[1] && inner[1][2];
                                        if (ts) {
                                            const d = new Date(ts / 1000);
                                            const m   = String(d.getMonth()+1).padStart(2,'0');
                                            const day = String(d.getDate()).padStart(2,'0');
                                            reviewDate = `${d.getFullYear()}-${m}-${day}`;
                                        }
                                    } catch(e) {}

                                    // Rating: r[0][2][0][0]
                                    let rating = null;
                                    try { rating = inner[2][0][0]; } catch(e) {}

                                    // Review text: r[0][2][15][0][0]
                                    let reviewText = "";
                                    try { reviewText = inner[2][15][0][0] || ""; } catch(e) {}

                                    // Owner reply block: r[0][3]
                                    let ownerReplyDate = null;
                                    let ownerReplyText = "";
                                    try {
                                        const rb = inner[3];
                                        if (rb) {
                                            // Owner reply date: rb[1] (microseconds)
                                            try {
                                                if (rb[1]) {
                                                    const od   = new Date(rb[1] / 1000);
                                                    const om   = String(od.getMonth()+1).padStart(2,'0');
                                                    const oday = String(od.getDate()).padStart(2,'0');
                                                    ownerReplyDate = `${od.getFullYear()}-${om}-${oday}`;
                                                }
                                            } catch(e) {}

                                            // Owner reply text: scan indices 6-18
                                            for (let i = 6; i <= 18; i++) {
                                                try {
                                                    const val = rb[i] && rb[i][0] && rb[i][0][0];
                                                    if (val && typeof val === "string" && val.length > 2) {
                                                        ownerReplyText = val;
                                                        break;
                                                    }
                                                } catch(e) {}
                                            }
                                        }
                                    } catch(e) {}

                                    window._reviewData[rid] = {
                                        reviewDate,
                                        rating,
                                        reviewText,
                                        ownerReplyText,
                                        ownerReplyDate,
                                    };

                                    // Debug: keep r[0][3] snapshot for first 20
                                    if (Object.keys(window._ownerDebug).length < 20) {
                                        window._ownerDebug[rid] = JSON.stringify(inner[3]).substring(0, 300);
                                    }

                                } catch(e) {
                                    window._ownerDebug['ERROR_' + Math.random()] = String(e);
                                }
                            });
                        } catch(e) {}
                    });
                    return _origOpen.apply(this, arguments);
                };
            '''
        })
        log.info("JS review data interceptor injected")
    except Exception as e:
        log.warning(f"Could not inject JS review data interceptor: {e}")
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


def poll_timestamp_responses(driver: Chrome, ts_cache: Dict[str, Any],
                             owner_cache: Dict[str, Any] = None) -> None:
    """
    Read all review data captured by the JS interceptor from window._reviewData
    into ts_cache. Each entry is a dict with keys:
        reviewDate, rating, reviewText, ownerReplyText, ownerReplyDate

    The owner_cache parameter is kept for backwards compatibility but is no
    longer needed — all data including owner reply fields flows into ts_cache.

    Call this inside the scroll loop on each iteration.
    """
    try:
        data = driver.execute_script("return window._reviewData || {};")
        if data:
            new = {k: v for k, v in data.items() if k not in ts_cache}
            if new:
                ts_cache.update(new)
                log.debug(f"JS poll: {len(new)} new reviews captured, total {len(ts_cache)}")
    except Exception as e:
        log.debug(f"JS poll error: {e}")

    # Debug: log r[0][3] snapshots to verify owner reply extraction
    try:
        debug = driver.execute_script("return window._ownerDebug || {};")
        if debug:
            log.info(f"DEBUG ownerDebug size: {len(debug)}")
            for rid, val in list(debug.items())[:5]:
                log.info(f"DEBUG r[0][3] for {rid}: {val}")
            driver.execute_script("window._ownerDebug = {};")
    except Exception as e:
        log.debug(f"JS owner debug error: {e}")
