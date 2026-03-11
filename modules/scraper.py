def scrape(self):
        """Main scraper method"""
        start_time = time.time()

        url = self.config.get("url")
        headless = self.config.get("headless", True)
        sort_by = self.config.get("sort_by", "relevance")
        stop_threshold = self.config.get("stop_threshold", 3)
        max_reviews = self.config.get("max_reviews", 0)
        max_scroll_attempts = self.config.get("max_scroll_attempts", 50)
        scroll_idle_limit = self.config.get("scroll_idle_limit", 15)

        log.info(f"Starting scraper with settings: headless={headless}, sort_by={sort_by}")
        log.info(f"URL: {url}")

        place_id = None
        session_id = None
        batch_stats = {"new": 0, "updated": 0, "restored": 0, "unchanged": 0}
        changed_ids = set()

        driver = None
        try:
            driver = self.setup_driver(headless)
            wait = WebDriverWait(driver, 20)

            self.navigate_to_place(driver, url, wait)

            resolved_url = driver.current_url
            place_name = ""
            try:
                title = driver.title or ""
                place_name = title.replace(" - Google Maps", "").strip()
            except Exception:
                pass
            place_id = extract_place_id(url, resolved_url)
            lat, lng = self._extract_place_coords(resolved_url)
            lat_f = float(lat) if lat else None
            lng_f = float(lng) if lng else None
            place_id = self.review_db.upsert_place(
                place_id, place_name, url, resolved_url, lat_f, lng_f
            )
            session_id = self.review_db.start_session(place_id, sort_by)
            log.info(f"Registered place: {place_id} ({place_name})")

            if self.scrape_mode == "full":
                seen = set()
            else:
                seen = self.review_db.get_review_ids(place_id)

            self.dismiss_cookies(driver)
            self.click_reviews_tab(driver)

            log.info("Waiting for reviews page to fully load...")
            time.sleep(3)

            try:
                wait.until(lambda d: d.execute_script("return document.readyState") == "complete")
                log.info("Page DOM is ready")
            except:
                log.debug("Could not verify page ready state")

            if "review" not in driver.current_url.lower():
                log.warning("URL doesn't contain 'review' - might not be on reviews page")

            sort_ok = False
            try:
                sort_ok = bool(self.set_sort(driver, sort_by))
            except Exception as sort_error:
                log.warning(f"Sort failed but continuing: {sort_error}")

            if stop_threshold > 0 and (not sort_ok or sort_by != "newest"):
                log.warning(
                    "Disabling early stop (stop_threshold=%d) — "
                    "reviews are not confirmed sorted by newest",
                    stop_threshold,
                )
                stop_threshold = 0

            log.info("Waiting for reviews to render...")
            time.sleep(3)

            pane = None
            pane_selectors = [
                PANE_SEL,
                'div[role="main"] div.m6QErb',
                'div.m6QErb.DxyBCb',
                'div[role="main"]'
            ]

            for selector in pane_selectors:
                try:
                    log.info(f"Trying to find reviews pane with selector: {selector}")
                    pane = wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, selector)))
                    if pane:
                        log.info(f"Found reviews pane with selector: {selector}")
                        break
                except TimeoutException:
                    log.debug(f"Pane not found with selector: {selector}")
                    continue

            if not pane:
                log.warning("Could not find reviews pane with any selector. Page structure might have changed.")
                return False

            progress = Progress(
                SpinnerColumn(),
                TextColumn("[bold blue]{task.description}"),
                BarColumn(),
                MofNCompleteColumn(),
                transient=False,
            )
            progress.start()
            task_id = progress.add_task("Scraped", total=None, completed=len(seen))
            idle = 0
            processed_ids = set()
            consecutive_matched_batches = 0

            try:
                driver.execute_script("window.scrollablePane = arguments[0];", pane)
                scroll_script = "window.scrollablePane.scrollBy(0, window.scrollablePane.scrollHeight);"
            except Exception as e:
                log.warning(f"Error setting up scroll script: {e}")
                scroll_script = "window.scrollBy(0, 300);"

            max_attempts = max_scroll_attempts
            attempts = 0
            max_idle = scroll_idle_limit
            consecutive_no_cards = 0
            last_scroll_position = 0
            scroll_stuck_count = 0

            while attempts < max_attempts:
                if self.cancel_event.is_set():
                    log.info("Scrape cancelled by user request")
                    raise InterruptedError("Scrape cancelled")

                try:
                    cards = pane.find_elements(By.CSS_SELECTOR, CARD_SEL)
                    fresh_cards: List[WebElement] = []

                    if len(cards) == 0:
                        consecutive_no_cards += 1
                        log.info(f"No review cards found in this iteration (consecutive: {consecutive_no_cards})")

                        if consecutive_no_cards > 5:
                            log.warning("No cards found for 5+ iterations - might be at end of reviews")
                            break

                        attempts += 1
                        driver.execute_script(scroll_script)
                        time.sleep(1)
                        driver.execute_script("window.scrollBy(0, 1000);")
                        time.sleep(1.5)
                        continue
                    else:
                        consecutive_no_cards = 0

                    batch_seen_count = 0
                    for c in cards:
                        try:
                            cid = c.get_attribute("data-review-id")
                            if not cid or cid in processed_ids:
                                continue
                            processed_ids.add(cid)
                            if cid in seen:
                                batch_seen_count += 1
                                continue
                            fresh_cards.append(c)
                        except StaleElementReferenceException:
                            continue
                        except Exception as e:
                            log.debug(f"Error getting review ID: {e}")
                            continue

                    batch_total = len(fresh_cards) + batch_seen_count
                    batch_unchanged = batch_seen_count

                    for card in fresh_cards:
                        try:
                            raw = RawReview.from_card(card)
                        except StaleElementReferenceException:
                            continue
                        except Exception:
                            log.warning("parse error - storing stub\n%s",
                                        traceback.format_exc(limit=1).strip())
                            try:
                                raw_id = card.get_attribute("data-review-id") or ""
                                raw = RawReview(id=raw_id, text="", lang="und")
                            except StaleElementReferenceException:
                                continue

                        review_dict = {
                            "review_id": raw.id,
                            "text": raw.text,
                            "rating": raw.rating,
                            "likes": raw.likes,
                            "lang": raw.lang,
                            "date": raw.date,
                            "review_date": raw.review_date,
                            "author": raw.author,
                            "profile": raw.profile,
                            "avatar": raw.avatar,
                            "owner_text": raw.owner_text,
                            "photos": raw.photos,
                        }
                        result = self.review_db.upsert_review(
                            place_id, review_dict, session_id,
                            scrape_mode=self.scrape_mode,
                        )
                        batch_stats[result] = batch_stats.get(result, 0) + 1
                        if result != "unchanged":
                            changed_ids.add(raw.id)
                        if result == "unchanged":
                            batch_unchanged += 1
                        seen.add(raw.id)
                        progress.advance(task_id)
                        idle = 0
                        attempts = 0

                        if max_reviews > 0 and len(seen) >= max_reviews:
                            log.info("Reached max_reviews limit (%d), stopping.", max_reviews)
                            idle = 999
                            break

                    if stop_threshold > 0 and batch_total >= 3:
                        if batch_unchanged == batch_total:
                            consecutive_matched_batches += 1
                            log.info("Fully matched batch %d/%d (%d reviews)",
                                     consecutive_matched_batches, stop_threshold, batch_total)
                            if consecutive_matched_batches >= stop_threshold:
                                log.info("Stopping: %d consecutive fully-matched batches",
                                         stop_threshold)
                                idle = 999
                        else:
                            consecutive_matched_batches = 0

                    if idle >= max_idle:
                        log.info(f"Stopping: No new reviews found after {max_idle} scroll attempts")
                        break

                    if not fresh_cards:
                        idle += 1
                        attempts += 1
                        log.info(f"No new reviews in this iteration (idle: {idle}/{max_idle}, attempts: {attempts}/{max_attempts}, total seen: {len(seen)})")

                        try:
                            driver.execute_script(scroll_script)
                            time.sleep(0.5)
                            driver.execute_script("window.scrollBy(0, 500);")
                            time.sleep(0.5)
                        except Exception as e:
                            log.warning(f"Error scrolling: {e}")
                    else:
                        log.info(f"Found {len(fresh_cards)} new reviews in this iteration")

                    # Check if we're actually scrolling or stuck
                    try:
                        current_scroll = driver.execute_script("return arguments[0].scrollTop;", pane)
                        if current_scroll == last_scroll_position and len(fresh_cards) == 0:
                            scroll_stuck_count += 1
                            log.warning(f"Scroll position hasn't changed (stuck at {current_scroll}px, stuck count: {scroll_stuck_count})")

                            if scroll_stuck_count == 3:
                                # Strategy 1: scroll last card into view
                                log.warning("Stuck - trying lastElementChild.scrollIntoView()")
                                try:
                                    driver.execute_script("arguments[0].lastElementChild.scrollIntoView();", pane)
                                    time.sleep(2)
                                except:
                                    pass

                            elif scroll_stuck_count == 6:
                                # Strategy 2: scroll via window instead of pane
                                log.warning("Still stuck - trying window.scrollBy fallback")
                                try:
                                    driver.execute_script("window.scrollBy(0, 2000);")
                                    time.sleep(2)
                                except:
                                    pass

                            elif scroll_stuck_count == 9:
                                # Strategy 3: click last card to wake up lazy loading
                                log.warning("Still stuck - clicking last card to trigger lazy load")
                                try:
                                    all_cards = pane.find_elements(By.CSS_SELECTOR, CARD_SEL)
                                    if all_cards:
                                        driver.execute_script("arguments[0].click();", all_cards[-1])
                                        time.sleep(1)
                                        driver.execute_script("arguments[0].scrollIntoView();", all_cards[-1])
                                        time.sleep(2)
                                except:
                                    pass

                            elif scroll_stuck_count == 12:
                                # Strategy 4: re-find pane and reset scroll script
                                log.warning("Still stuck - re-finding pane and resetting scroll")
                                try:
                                    pane = driver.find_element(By.CSS_SELECTOR, PANE_SEL)
                                    driver.execute_script("window.scrollablePane = arguments[0];", pane)
                                    scroll_script = "window.scrollablePane.scrollBy(0, window.scrollablePane.scrollHeight);"
                                    driver.execute_script(scroll_script)
                                    time.sleep(3)
                                except:
                                    pass

                            elif scroll_stuck_count >= 15:
                                # Give up - truly at end of reviews
                                log.warning("Scroll permanently stuck after 15 attempts - stopping")
                                break

                        else:
                            scroll_stuck_count = 0
                            last_scroll_position = current_scroll
                    except:
                        pass

                    # Use JavaScript for smoother scrolling
                    try:
                        driver.execute_script(scroll_script)
                    except Exception as e:
                        log.warning(f"Error scrolling: {e}")
                        driver.execute_script("window.scrollBy(0, 300);")

                    # Dynamic sleep
                    if len(fresh_cards) > 5:
                        sleep_time = 0.7
                    elif len(fresh_cards) == 0:
                        sleep_time = 2.0
                    else:
                        sleep_time = 1.0
                    time.sleep(sleep_time)

                except StaleElementReferenceException:
                    log.debug("Stale element encountered, re-finding elements")
                    try:
                        pane = wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, PANE_SEL)))
                        driver.execute_script("window.scrollablePane = arguments[0];", pane)
                    except Exception:
                        log.warning("Could not re-find reviews pane after stale element")
                        break
                except Exception as e:
                    log.warning(f"Error during review processing: {e}")
                    attempts += 1
                    time.sleep(1)

            progress.stop()

            total_found = sum(batch_stats.values())
            if session_id:
                self.review_db.end_session(
                    session_id, "completed",
                    reviews_found=total_found,
                    reviews_new=batch_stats.get("new", 0),
                    reviews_updated=(
                        batch_stats.get("updated", 0)
                        + batch_stats.get("restored", 0)
                    ),
                )

            reviews = self.review_db.get_reviews(place_id) if place_id else []
            if reviews:
                legacy_docs = {
                    r["review_id"]: self._db_review_to_legacy(r) for r in reviews
                }
                runner = PostScrapeRunner(self.config)
                try:
                    runner.run(legacy_docs, place_id, seen=seen)
                finally:
                    runner.close()

            log.info(
                "Finished - new: %d, updated: %d, restored: %d, unchanged: %d",
                batch_stats["new"], batch_stats["updated"],
                batch_stats["restored"], batch_stats["unchanged"],
            )
            log.info("Total unique reviews in DB: %d", len(reviews))

            end_time = time.time()
            elapsed_time = end_time - start_time
            log.info(f"Execution completed in {elapsed_time:.2f} seconds")

            return True

        except Exception as e:
            if session_id:
                self.review_db.end_session(session_id, "failed", error=str(e))
            log.error(f"Error during scraping: {e}")
            log.error(traceback.format_exc())
            return False

        finally:
            if driver is not None:
                try:
                    driver.quit()
                except Exception:
                    pass
