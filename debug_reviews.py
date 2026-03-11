"""
Scan Google Maps review cards to find the real owner response CSS selector.
Run from your google-reviews-scraper-pro folder.
"""
import time
from seleniumbase import Driver
from selenium.webdriver.common.by import By

URL = "https://www.google.com/maps/place/Validated+Claim+Support/@40.8725539,-74.0086251,17z/data=!3m1!5s0x89c2fa0350b2533f:0x35c38163899d309b!4m8!3m7!1s0x89c2f70e34150509:0x8e0802c97d8f73cc!8m2!3d40.8725539!4d-74.0060502!9m1!1b1!16s%2Fg%2F11fn1rmh8n?entry=ttu&g_ep=EgoyMDI2MDMwOS4wIKXMDSoASAFQAw%3D%3D"

driver = Driver(uc=True, headless=False)
driver.get(URL)
time.sleep(5)

# Click reviews tab
tabs = driver.find_elements(By.CSS_SELECTOR, '[role="tab"]')
for t in tabs:
    if "review" in (t.text or "").lower() or t.get_attribute("data-tab-index") == "1":
        t.click()
        time.sleep(3)
        break

# Scroll a bit to load more reviews
driver.execute_script("window.scrollBy(0, 800)")
time.sleep(2)

cards = driver.find_elements(By.CSS_SELECTOR, "div[data-review-id]")
print(f"Found {len(cards)} cards\n")

found_any = False
for i, card in enumerate(cards[:30]):
    # Check if old selector still works
    old = card.find_elements(By.CSS_SELECTOR, "div.CDe7pd")
    if old:
        print(f"Card {i}: OLD selector div.CDe7pd still works!")
        print(f"  text: {old[0].text[:150]}")
        found_any = True
        continue

    # Search all divs in this card for owner response text
    divs = card.find_elements(By.CSS_SELECTOR, "div")
    for d in divs:
        try:
            txt = (d.text or "").strip()
            cls = (d.get_attribute("class") or "").strip()
            # Owner responses typically contain these phrases
            triggers = ["response from the owner", "owner", "thank you", "hi ", "hello"]
            if txt and 10 < len(txt) < 500 and any(kw in txt.lower() for kw in triggers):
                # Make sure it's not just the review text itself
                review_txt = card.find_elements(By.CSS_SELECTOR, "span.wiI7pd")
                review_text_val = review_txt[0].text if review_txt else ""
                if txt != review_text_val:
                    print(f"Card {i}: POSSIBLE owner response")
                    print(f"  class: '{cls}'")
                    print(f"  text:  '{txt[:150]}'")
                    found_any = True
        except Exception:
            continue

if not found_any:
    print("No owner responses found in the first 30 cards.")
    print("Either no reviews have owner responses, or the page didn't load them.")
    print("\nTip: scroll the page manually to a review with an owner response,")
    print("then press Enter to scan again.")
    input("Press Enter to scan visible cards again...")
    cards = driver.find_elements(By.CSS_SELECTOR, "div[data-review-id]")
    for i, card in enumerate(cards):
        divs = card.find_elements(By.CSS_SELECTOR, "div")
        for d in divs:
            try:
                txt = (d.text or "").strip()
                cls = (d.get_attribute("class") or "").strip()
                if txt and 10 < len(txt) < 500 and "owner" in txt.lower():
                    print(f"Card {i} | class='{cls}' | '{txt[:150]}'")
            except Exception:
                continue

input("\nDone. Press Enter to close browser...")
driver.quit()