"""
Data models for Google Maps Reviews Scraper.
"""
import re
import time
from dataclasses import dataclass, field
from selenium.webdriver.remote.webelement import WebElement
from modules.utils import (try_find, first_text, first_attr, safe_int, detect_lang, parse_date_to_iso)


@dataclass
class RawReview:
    """
    Data class representing a raw review extracted from Google Maps.
    """
    id: str = ""
    author: str = ""
    rating: float = 0.0
    date: str = ""
    lang: str = "und"
    text: str = ""
    likes: int = 0
    photos: list[str] = field(default_factory=list)
    profile: str = ""
    avatar: str = ""
    owner_date: str = ""
    owner_text: str = ""
    review_date: str = ""

    # Translation fields
    translations: dict = field(default_factory=dict)

    # CSS Selectors for review elements
    MORE_BTN = "button.kyuRq"
    LIKE_BTN = 'button[jsaction*="toggleThumbsUp" i]'
    PHOTO_BTN = "button.Tya61d"

    # Owner response container selectors (tried in order)
    OWNER_RESP_SELECTORS = [
        "div.CDe7pd",
        "div.d9rcMe",
        "div[class*='CDe7pd']",
        "div[class*='d9rcMe']",
        "div[jslog*='owner']",
    ]
    OWNER_TEXT_SELECTORS = [
        "div.wiI7pd",
        "span.wiI7pd",
        "div[class*='wiI7pd']",
    ]
    OWNER_DATE_SELECTORS = [
        "span.DZSIDd",
        "span[class*='DZSIDd']",
    ]

    # Prefix lines that Google prepends to owner response containers
    _OWNER_HEADER_PREFIXES = (
        "response from the owner",
        "תגובת הבעלים",
        "คำตอบจากเจ้าของ",
        "réponse du propriétaire",
        "respuesta del propietario",
        "risposta del proprietario",
        "antwort des inhabers",
        "resposta do proprietário",
        "ответ владельца",
        "オーナーからの返信",
        "업주의 답변",
        "来自业主的回复",
        "來自業主的回覆",
    )

    @classmethod
    def _strip_owner_header(cls, raw: str, owner_date: str) -> str:
        """
        Strip the 'Response from the owner X ago' header line(s) from the
        raw container text, leaving only the actual reply body.
        """
        lines = raw.strip().splitlines()
        result = []
        for line in lines:
            stripped = line.strip()
            if not stripped:
                continue
            lower = stripped.lower()
            # Skip the "Response from the owner" label line
            if any(lower.startswith(p) for p in cls._OWNER_HEADER_PREFIXES):
                continue
            # Skip the date line if we already have it
            if owner_date and stripped == owner_date:
                continue
            result.append(stripped)
        return "\n".join(result).strip()

    @classmethod
    def from_card(cls, card: WebElement) -> "RawReview":
        """Factory method to create a RawReview from a WebElement"""
        # Expand "More" - non-blocking approach
        for b in try_find(card, cls.MORE_BTN, all=True):
            try:
                b.click()
                time.sleep(0.4)
            except Exception:
                pass

        rid     = card.get_attribute("data-review-id") or ""
        author  = first_text(card, 'div[class*="d4r55"]')
        profile = first_attr(card, 'button[data-review-id]', "data-href")
        avatar  = first_attr(card, 'button[data-review-id] img', "src")

        label = first_attr(card, 'span[role="img"]', "aria-label")
        num   = re.search(r"[\d\.]+", label.replace(",", ".")) if label else None
        rating = float(num.group()) if num else 0.0

        date        = first_text(card, 'span[class*="rsqaWe"]')
        review_date = parse_date_to_iso(date)

        text = ""
        for sel in ('span[jsname="bN97Pc"]',
                    'span[jsname="fbQN7e"]',
                    'div.MyEned span.wiI7pd'):
            text = first_text(card, sel)
            if text:
                break
        lang = detect_lang(text)

        likes = 0
        if (btn := try_find(card, cls.LIKE_BTN)):
            likes = safe_int(btn[0].text or btn[0].get_attribute("aria-label"))

        photos: list[str] = []
        for btn in try_find(card, cls.PHOTO_BTN, all=True):
            if (m := re.search(r'url\("([^"]+)"', btn.get_attribute("style") or "")):
                photos.append(m.group(1))

        # --- Owner response ---
        owner_date = owner_text = ""
        box = None

        # Try each container selector in order
        for sel in cls.OWNER_RESP_SELECTORS:
            found = try_find(card, sel, all=True)
            if found:
                box = found[0]
                break

        if box:
            # Try dedicated date selector
            for sel in cls.OWNER_DATE_SELECTORS:
                owner_date = first_text(box, sel)
                if owner_date:
                    break

            # Try dedicated text selector
            for sel in cls.OWNER_TEXT_SELECTORS:
                owner_text = first_text(box, sel)
                if owner_text:
                    break

            # Fallback: strip header lines from full container text
            if not owner_text and box.text:
                owner_text = cls._strip_owner_header(box.text, owner_date)
                
            # Convert owner_date to ISO format *after* it was used to strip the header
            if owner_date:
                owner_date = parse_date_to_iso(owner_date)

        return cls(rid, author, rating, date, lang, text, likes,
                   photos, profile, avatar, owner_date, owner_text, review_date)