import os
import sys
import subprocess
import time
import random
import threading
import urllib.parse
import uuid
import datetime
import requests
from typing import List, Dict, Optional, Tuple
from insta_bot.database import add_reel_log, is_reel_already_sent

import re

_PLAYWRIGHT_READY = False

def ensure_playwright_ready(log_func=None):
    """
    Ensure Playwright Chromium browser is installed and ready in the environment.
    Runs asynchronously in background or synchronously as needed.
    """
    global _PLAYWRIGHT_READY
    if _PLAYWRIGHT_READY:
        return
        
    def _install_worker():
        global _PLAYWRIGHT_READY
        try:
            res = subprocess.run(
                [sys.executable, "-m", "playwright", "install", "chromium"],
                capture_output=True,
                text=True,
                timeout=180
            )
            if res.returncode == 0:
                _PLAYWRIGHT_READY = True
                if log_func:
                    log_func("✅ Playwright Chromium browser verified & ready.")
        except Exception as e:
            if log_func:
                log_func(f"⚠️ Playwright background check note: {e}")

    t = threading.Thread(target=_install_worker, daemon=True)
    t.start()


def safe_launch_playwright_browser(p, headless: bool = True, log_func=None):
    """
    Safely launch Playwright Chromium browser across environments (Streamlit Community Cloud, Linux, Mac, Windows).
    1. Attempts standard launch.
    2. If missing, attempts to use system-installed Chromium (/usr/bin/chromium from packages.txt).
    3. If still missing, automatically installs Chromium via `python -m playwright install chromium` and launches.
    """
    launch_args = [
        "--disable-blink-features=AutomationControlled",
        "--no-sandbox",
        "--disable-dev-shm-usage",
        "--disable-gpu"
    ]
    
    # Attempt 1: Standard launch
    try:
        return p.chromium.launch(headless=headless, args=launch_args)
    except Exception as e1:
        err_str = str(e1)
        if log_func:
            log_func(f"⚠️ Standard browser launch notice: {err_str[:110]}... Attempting auto-recovery...")

    # Attempt 2: Use system chromium installed via packages.txt
    system_paths = [
        "/usr/bin/chromium",
        "/usr/bin/chromium-browser",
        "/usr/bin/google-chrome",
        "/usr/bin/google-chrome-stable"
    ]
    for sp in system_paths:
        if os.path.exists(sp):
            try:
                if log_func:
                    log_func(f"🌐 Using system installed Chromium at {sp}...")
                return p.chromium.launch(executable_path=sp, headless=headless, args=launch_args)
            except Exception as e_sys:
                if log_func:
                    log_func(f"⚠️ System Chromium launch note: {e_sys}")

    # Attempt 3: Auto-install browser binaries on server (e.g. Streamlit Community Cloud)
    if log_func:
        log_func("📦 Auto-installing Playwright Chromium binaries on server... (Please wait ~20-30s)")
    try:
        run_res = subprocess.run(
            [sys.executable, "-m", "playwright", "install", "chromium"],
            capture_output=True,
            text=True,
            timeout=180
        )
        if run_res.returncode == 0 and log_func:
            log_func("✅ Playwright Chromium binaries installed successfully!")
        
        return p.chromium.launch(headless=headless, args=launch_args)
    except Exception as e3:
        if log_func:
            log_func(f"❌ Failed to auto-install Playwright browser: {e3}")
        raise e3


def is_valid_reel_url(url: str) -> bool:
    """Validate that a URL points to an actual single Reel post, not the generic reels feed, audio, or stories page."""
    if not url or "/audio/" in url or "/tagged/" in url or "/stories/" in url:
        return False
    clean = url.split("?")[0].rstrip("/")
    match = re.search(r'instagram\.com/(?:reel|reels|p)/([A-Za-z0-9_-]+)', clean)
    if not match:
        return False
    shortcode = match.group(1).strip()
    return len(shortcode) >= 5 and shortcode.lower() not in ["reels", "reel", "explore", "feed", "audio", "stories"]


def parse_time_str(t_str: str) -> Tuple[int, int]:
    """Parse time string in 12-hour AM/PM format (e.g. '09:00 PM', '9 PM', '09:00PM') or 24-hour format (e.g. '21:00')."""
    if not t_str or not t_str.strip():
        return 21, 0
    raw_str = t_str.strip().upper()

    for fmt in ["%I:%M %p", "%I:%M%p", "%I %p", "%I%p", "%H:%M"]:
        try:
            dt = datetime.datetime.strptime(raw_str, fmt)
            return dt.hour, dt.minute
        except ValueError:
            pass

    match = re.search(r'(\d{1,2})(?::(\d{2}))?\s*(AM|PM)?', raw_str)
    if match:
        h = int(match.group(1))
        m = int(match.group(2)) if match.group(2) else 0
        ampm = match.group(3)
        if ampm == "PM" and h < 12:
            h += 12
        elif ampm == "AM" and h == 12:
            h = 0
        return h, m

    return 21, 0

class ReelAutomationEngine:
    def __init__(self, sessionid: str = ""):
        self.sessionid = sessionid.strip()
        self.is_running = False
        self.is_paused = False
        self.status = "IDLE"
        self.logs: List[str] = []
        self.sent_count = 0
        self.failed_count = 0
        self.total_reels = 0
        self.next_run_timestamp: Optional[float] = None
        self.thread: Optional[threading.Thread] = None

    def log(self, message: str):
        timestamp = datetime.datetime.now().strftime("%H:%M:%S")
        formatted = f"[{timestamp}] {message}"
        self.logs.append(formatted)
        print(formatted)

    def verify_sessionid(self, sessionid: Optional[str] = None) -> Tuple[bool, str, str]:
        """
        Verify Instagram Session ID cookie by attempting authenticated web API calls.
        Returns: (is_valid, username, message)
        """
        raw_sid = (sessionid or self.sessionid).strip().strip('"').strip("'")
        if not raw_sid or len(raw_sid) < 5:
            return False, "", "Session ID is empty or too short."

        clean_sid = urllib.parse.unquote(raw_sid)
        ds_user_id = clean_sid.split("%3A")[0] if "%3A" in clean_sid else clean_sid.split(":")[0]

        temp_sid = self.sessionid
        self.sessionid = clean_sid
        s = self._authed_session()
        self.sessionid = temp_sid

        try:
            # 0. Check Root Page redirect status first
            r_root = s.get("https://www.instagram.com/", allow_redirects=False, timeout=8)
            if r_root.status_code == 302 and "login" in r_root.headers.get("Location", "").lower():
                return False, "", "Session ID cookie is invalid, expired, or logged out on Instagram."

            # 1. Primary Endpoint: Accounts current_user
            res = s.get("https://www.instagram.com/api/v1/accounts/current_user/?edit=true", allow_redirects=False, timeout=10)
            if res.status_code == 200:
                u_data = res.json().get("user", {})
                username = u_data.get("username", "") or ""
                full_name = u_data.get("full_name", "") or ""
                if username:
                    fn_str = f" ({full_name})" if full_name else ""
                    return True, username, f"Session ID Verified! Connected as @{username}{fn_str}"
                return True, ds_user_id, f"Session ID Active! Connected User ID: {ds_user_id}"

            # 2. Secondary Endpoint Fallback: Direct Inbox check
            res2 = s.get("https://www.instagram.com/api/v1/direct_v2/inbox/?persistent_badging=true", allow_redirects=False, timeout=10)
            if res2.status_code == 200:
                user_obj = res2.json().get("viewer", {}) or {}
                username = user_obj.get("username", "") or ds_user_id or "Authenticated User"
                return True, username, f"Session ID Verified! Connected as @{username}"

            if res.status_code in [301, 302, 303, 307, 400, 401, 403, 404] or res2.status_code in [301, 302, 303, 307, 400, 401, 403, 404]:
                return False, "", "Session ID cookie is invalid, expired, or unauthorized."
            else:
                return False, "", f"Session ID verification failed (Instagram HTTP {res.status_code})"
        except Exception as err:
            return False, "", f"Verification failed: {err}"

    def _authed_session(self) -> requests.Session:
        """Create an authenticated HTTP session using sessionid cookie with full IG Web headers."""
        s = requests.Session()
        raw_sid = self.sessionid.strip().strip('"').strip("'")
        clean_sid = urllib.parse.unquote(raw_sid)
        ds_user_id = clean_sid.split("%3A")[0] if "%3A" in clean_sid else clean_sid.split(":")[0]
        
        s.headers.update({
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            "X-IG-App-ID": "936619743392459",
            "X-Requested-With": "XMLHttpRequest",
            "X-Instagram-AJAX": "1006888632",
            "Referer": "https://www.instagram.com/direct/inbox/",
            "Origin": "https://www.instagram.com",
            "Accept": "*/*",
            "Accept-Language": "en-US,en;q=0.9"
        })
        
        csrf_token = uuid.uuid4().hex
        # Set cookies cleanly on single domain to avoid CookieConflictError
        s.cookies.set("sessionid", raw_sid, domain=".instagram.com", path="/")
        if ds_user_id:
            s.cookies.set("ds_user_id", ds_user_id, domain=".instagram.com", path="/")
        s.cookies.set("csrftoken", csrf_token, domain=".instagram.com", path="/")
        
        s.headers["X-CSRFToken"] = csrf_token

        # Fetch real csrftoken from Instagram
        try:
            r = s.get("https://www.instagram.com/api/v1/accounts/current_user/?edit=true", allow_redirects=False, timeout=5)
            real_csrf = s.cookies.get("csrftoken", domain=".instagram.com")
            if real_csrf:
                s.headers["X-CSRFToken"] = real_csrf
        except Exception:
            pass
            
        return s

    def resolve_user_id(self, username: str) -> Optional[str]:
        """
        Resolve numeric Instagram User ID for a target username with multiple resilient fallbacks:
        1. Web Profile Info endpoint
        2. Topsearch / Search API endpoint
        3. User lookup / search endpoint
        4. Profile JSON endpoint (__a=1)
        """
        clean_username = username.strip().lstrip("@")
        s = self._authed_session()

        # Method 1: Web profile info
        try:
            res = s.get(f"https://www.instagram.com/api/v1/users/web_profile_info/?username={clean_username}", allow_redirects=False, timeout=8)
            if res.status_code == 200:
                uid = res.json().get("data", {}).get("user", {}).get("id")
                if uid:
                    return str(uid)
        except Exception as e:
            self.log(f"⚠️ Resolution method 1 notice for @{clean_username}: {e}")

        # Method 2: Instagram Topsearch API
        try:
            res2 = s.get(f"https://www.instagram.com/web/search/topsearch/?context=blended&query={clean_username}&rank_token=0.5", timeout=8)
            if res2.status_code == 200:
                for item in res2.json().get("users", []):
                    u = item.get("user", {})
                    if u.get("username", "").lower() == clean_username.lower():
                        uid = u.get("pk") or u.get("id")
                        if uid:
                            return str(uid)
        except Exception as e:
            self.log(f"⚠️ Resolution method 2 notice for @{clean_username}: {e}")

        # Method 3: User search endpoint
        try:
            res3 = s.get(f"https://www.instagram.com/api/v1/users/search/?q={clean_username}&count=10", timeout=8)
            if res3.status_code == 200:
                for u in res3.json().get("users", []):
                    if u.get("username", "").lower() == clean_username.lower():
                        uid = u.get("pk") or u.get("id")
                        if uid:
                            return str(uid)
        except Exception as e:
            self.log(f"⚠️ Resolution method 3 notice for @{clean_username}: {e}")

        # Method 4: Public profile JSON (__a=1)
        try:
            res4 = s.get(f"https://www.instagram.com/{clean_username}/?__a=1&__d=dis", timeout=8)
            if res4.status_code == 200:
                data = res4.json()
                uid = (
                    data.get("graphql", {}).get("user", {}).get("id") or
                    data.get("user", {}).get("id") or
                    data.get("user", {}).get("pk")
                )
                if uid:
                    return str(uid)
        except Exception as e:
            self.log(f"⚠️ Resolution method 4 notice for @{clean_username}: {e}")

        return None

    def discover_random_reels_from_feed(self, count: int = 5, headless: bool = True) -> List[str]:
        """
        Automatically scroll Instagram Reels Feed using Playwright and discover random fresh Reel URLs.
        """
        raw_sid = self.sessionid.strip().strip('"').strip("'")
        clean_sid = urllib.parse.unquote(raw_sid)
        ds_user_id = clean_sid.split("%3A")[0] if "%3A" in clean_sid else clean_sid.split(":")[0]

        if not raw_sid or len(raw_sid) < 5:
            self.log("❌ Cannot discover Reels: Session ID is empty or invalid.")
            return []

        discovered_reels = set()
        self.log(f"🎬 Scrolling Instagram Reels feed via Playwright to discover {count} random Reels...")

        try:
            from playwright.sync_api import sync_playwright
            with sync_playwright() as p:
                browser = safe_launch_playwright_browser(p, headless=headless, log_func=self.log)
                context = browser.new_context(
                    user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
                    viewport={"width": 1280, "height": 800}
                )
                context.add_cookies([
                    {"name": "sessionid", "value": raw_sid, "domain": ".instagram.com", "path": "/"},
                    {"name": "ds_user_id", "value": ds_user_id, "domain": ".instagram.com", "path": "/"}
                ])
                page = context.new_page()
                page.goto("https://www.instagram.com/reels/", timeout=40000, wait_until="domcontentloaded")
                time.sleep(3)

                for p_text in ["Not Now", "not now", "Save Info"]:
                    try:
                        b = page.locator(f"button:has-text('{p_text}')").first
                        if b.is_visible(timeout=1500):
                            b.click()
                            time.sleep(1)
                    except Exception:
                        pass

                max_scrolls = max(count * 3, 15)
                for _ in range(max_scrolls):
                    curr_u = page.url
                    if is_valid_reel_url(curr_u):
                        clean_url = curr_u.split("?")[0].rstrip("/") + "/"
                        discovered_reels.add(clean_url)

                    try:
                        hrefs = page.evaluate("""() => {
                            return Array.from(document.querySelectorAll("a[href*='/reel/'], a[href*='/reels/'], a[href*='/p/']"))
                                .map(el => el.href);
                        }""")
                        for full_link in hrefs:
                            clean_link = full_link.split("?")[0].rstrip("/") + "/"
                            if is_valid_reel_url(clean_link):
                                discovered_reels.add(clean_link)
                    except Exception:
                        pass

                    if len(discovered_reels) >= count:
                        break

                    page.keyboard.press("ArrowDown")
                    time.sleep(2)

                browser.close()

        except Exception as err:
            self.log(f"⚠️ Error discovering feed Reels: {err}")

        result_list = list(discovered_reels)
        self.log(f"🎉 Discovered {len(result_list)} random Reels from Instagram feed.")
        return result_list

    def send_direct_reel(self, recipient_username: str, reel_url: str, use_playwright: bool = True, headless: bool = True, force_resend: bool = False, max_retries: int = 2, page = None) -> bool:
        """
        Send a Reel link via Instagram Direct Message with automatic retry on failure.
        Prevents sending duplicate Reels to the same user.
        Uses Playwright real browser automation by default with persistent page reuse support.
        """
        if not force_resend and is_reel_already_sent(recipient_username, reel_url):
            msg = f"Reel ({reel_url}) was ALREADY SENT to @{recipient_username} previously. Skipping duplicate!"
            self.log(f"⚠️ {msg}")
            add_reel_log(recipient_username, reel_url, "SKIPPED", msg)
            return False

        for attempt in range(1, max_retries + 1):
            if attempt > 1:
                self.log(f"🔄 Retry Attempt {attempt}/{max_retries} for sending Reel to @{recipient_username}...")
                time.sleep(3)

            success = False
            if use_playwright:
                try:
                    success = self.send_direct_reel_playwright(recipient_username, reel_url, headless=headless, page=page)
                except Exception as err:
                    self.log(f"⚠️ Playwright engine error (Attempt {attempt}): {err}. Falling back to HTTP API...")
                    success = self._send_direct_reel_http(recipient_username, reel_url)
            else:
                success = self._send_direct_reel_http(recipient_username, reel_url)

            if success:
                return True
            else:
                self.log(f"❌ Send failed on attempt {attempt}/{max_retries}.")

        return False



    def send_direct_reel_playwright(self, recipient_username: str, reel_url: str, headless: bool = True, page = None) -> bool:
        """
        Send a Reel video card via Instagram Direct Message using Playwright Browser Automation.
        Navigates directly to the Reel page, clicks native Share button, selects recipient, and sends.
        Injects sessionid cookie into a real Chromium browser context with anti-detect stealth scripts.
        Reuses existing page when available to maintain continuous human-like browsing session.
        """
        clean_username = recipient_username.strip().lstrip("@")
        clean_sid = urllib.parse.unquote(self.sessionid.strip().strip('"').strip("'"))
        ds_user_id = clean_sid.split("%3A")[0] if "%3A" in clean_sid else clean_sid.split(":")[0]

        if not clean_sid or len(clean_sid) < 5:
            msg = "Session ID is empty or invalid."
            self.log(f"❌ {msg}")
            add_reel_log(recipient_username, reel_url, "FAILED", msg)
            return False

        def _do_send_on_page(target_page) -> bool:
            # Step 1: Open Reel URL directly
            self.log(f"🔗 Opening Reel URL: {reel_url}...")
            target_page.goto(reel_url, timeout=40000, wait_until="domcontentloaded")
            time.sleep(3)

            # Check if redirected to login page
            if "/accounts/login/" in target_page.url:
                msg = "Session ID cookie is invalid, expired, or logged out on Instagram."
                self.log(f"❌ Playwright Error: {msg}")
                add_reel_log(recipient_username, reel_url, "FAILED", msg)
                return False

            # Handle popups ("Not Now", "Save Info")
            for popup_text in ["Not Now", "not now", "Save Info"]:
                try:
                    btn = target_page.locator(f"button:has-text('{popup_text}'), div[role='button']:has-text('{popup_text}')").first
                    if btn.is_visible(timeout=1500):
                        btn.click()
                        time.sleep(1)
                except Exception:
                    pass

            # Step 2: Native Reel Share button click
            self.log("📲 Clicking native Reel Share button...")
            share_svg = target_page.locator("svg[aria-label='Share'], svg[aria-label='Share Post']").first
            share_success = False

            if share_svg.is_visible(timeout=5000):
                share_svg.click()
                time.sleep(2.5)

                search_input = target_page.locator("input[name='queryBox'], input[placeholder*='Search'], input[type='text']").first
                if search_input.is_visible(timeout=5000):
                    self.log(f"🔍 Searching for recipient @{clean_username} in Share dialog...")
                    search_input.fill(clean_username)
                    time.sleep(2)

                    user_row = target_page.locator(f"span:has-text('{clean_username}'), div:has-text('{clean_username}')").last
                    if user_row.is_visible(timeout=5000):
                        user_row.click()
                        time.sleep(1.5)

                        send_btn = target_page.locator("div[role='button']:has-text('Send'), button:has-text('Send')").first
                        if send_btn.is_visible(timeout=5000):
                            send_btn.click()
                            time.sleep(4)
                            share_success = True
                            msg = f"Successfully shared Reel video card with @{clean_username}!"
                            self.log(f"✅ {msg}: {reel_url}")
                            add_reel_log(recipient_username, reel_url, "SENT", msg)
                            return True

            # Fallback Step 3: DM text composer fallback if native Share button modal was skipped
            if not share_success:
                self.log("⚠️ Falling back to Direct Message compose box...")
                target_page.goto("https://www.instagram.com/direct/new/", timeout=30000, wait_until="domcontentloaded")
                time.sleep(3)

                search_box = target_page.locator("input[name='queryBox'], input[placeholder*='Search']").first
                if search_box.is_visible(timeout=5000):
                    search_box.fill(clean_username)
                    time.sleep(2)
                    
                    user_item = target_page.locator(f"span:has-text('{clean_username}'), div:has-text('{clean_username}')").last
                    if user_item.is_visible(timeout=5000):
                        user_item.click()
                        time.sleep(1)

                        next_btn = target_page.locator("div[role='button']:has-text('Next'), div[role='button']:has-text('Chat'), button:has-text('Next'), button:has-text('Chat')").first
                        if next_btn.is_visible(timeout=3000):
                            next_btn.click()
                            time.sleep(3)

                target_box = None
                selectors = [
                    "p[contenteditable='true']",
                    "div[contenteditable='true']",
                    "div[role='textbox']",
                    "div[aria-label*='Message']",
                    "textarea[placeholder*='Message']"
                ]

                for sel in selectors:
                    try:
                        box = target_page.wait_for_selector(sel, timeout=5000)
                        if box and box.is_visible():
                            target_box = box
                            break
                    except Exception:
                        pass

                if not target_box:
                    msg = f"Could not locate DM chat box for @{clean_username} on URL: {target_page.url}"
                    self.log(f"❌ {msg}")
                    add_reel_log(recipient_username, reel_url, "FAILED", msg)
                    return False

                target_box.click()
                time.sleep(0.5)
                target_box.fill(reel_url.strip())
                time.sleep(1)
                target_page.keyboard.press("Enter")
                time.sleep(4)

                msg = f"Successfully sent Reel to @{clean_username} via DM compose fallback!"
                self.log(f"✅ {msg}: {reel_url}")
                add_reel_log(recipient_username, reel_url, "SENT", msg)
                return True

            return False

        if page is not None:
            return _do_send_on_page(page)

        try:
            from playwright.sync_api import sync_playwright
            self.log(f"🌐 Launching Playwright Chromium Browser for @{clean_username} (Headless: {headless})...")
            
            with sync_playwright() as p:
                browser = safe_launch_playwright_browser(p, headless=headless, log_func=self.log)
                context = browser.new_context(
                    user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
                    viewport={"width": 1280, "height": 800}
                )
                context.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined});")

                raw_sid = self.sessionid.strip().strip('"').strip("'")
                cookies = [
                    {"name": "sessionid", "value": raw_sid, "domain": ".instagram.com", "path": "/"},
                    {"name": "ds_user_id", "value": ds_user_id, "domain": ".instagram.com", "path": "/"}
                ]
                context.add_cookies(cookies)

                single_page = context.new_page()
                res = _do_send_on_page(single_page)
                browser.close()
                return res

        except Exception as err:
            self.log(f"⚠️ Playwright automation note for @{clean_username}: {err}")
            self.log("🔄 Falling back to HTTP Direct API...")
            return self._send_direct_reel_http(recipient_username, reel_url)

    def _send_direct_reel_http(self, recipient_username: str, reel_url: str) -> bool:

        """Send a Reel link via Instagram Direct Message using HTTP API requests."""
        user_id = self.resolve_user_id(recipient_username)
        if not user_id:
            msg = f"Failed to find user ID for @{recipient_username}"
            self.log(f"❌ {msg}")
            add_reel_log(recipient_username, reel_url, "FAILED", msg)
            return False

        s = self._authed_session()
        client_context = str(uuid.uuid4().int)[:18]
        
        # Primary Payload: Direct text DM with Reel Link
        payload = {
            "recipient_users": f"[[{user_id}]]",
            "text": reel_url.strip(),
            "client_context": client_context,
            "action": "send_item"
        }
        
        try:
            res = s.post(
                "https://www.instagram.com/api/v1/direct_v2/threads/broadcast/text/",
                data=payload,
                allow_redirects=False,
                timeout=12
            )
            
            if res.status_code == 200 and res.json().get("status") == "ok":
                msg = f"Successfully sent Reel to @{recipient_username}"
                self.log(f"✅ {msg}: {reel_url}")
                add_reel_log(recipient_username, reel_url, "SENT", msg)
                return True
            elif res.status_code in [301, 302, 303, 307]:
                msg = "Session ID cookie is expired or unauthorized (Instagram redirected to login page)."
                self.log(f"❌ Error sending to @{recipient_username}: {msg}")
                add_reel_log(recipient_username, reel_url, "FAILED", msg)
                return False
            else:
                # Fallback Endpoint 2: Direct link DM broadcast
                link_payload = {
                    "recipient_users": f"[[{user_id}]]",
                    "link_text": reel_url.strip(),
                    "link_urls": f"[\"{reel_url.strip()}\"]",
                    "client_context": client_context,
                    "action": "send_item"
                }
                res2 = s.post(
                    "https://www.instagram.com/api/v1/direct_v2/threads/broadcast/link/",
                    data=link_payload,
                    allow_redirects=False,
                    timeout=12
                )
                if res2.status_code == 200 and res2.json().get("status") == "ok":
                    msg = f"Successfully sent Reel link to @{recipient_username}"
                    self.log(f"✅ {msg}: {reel_url}")
                    add_reel_log(recipient_username, reel_url, "SENT", msg)
                    return True
                elif res2.status_code in [301, 302, 303, 307]:
                    msg = "Session ID cookie is expired or unauthorized (Instagram redirected to login page)."
                    self.log(f"❌ Error sending to @{recipient_username}: {msg}")
                    add_reel_log(recipient_username, reel_url, "FAILED", msg)
                    return False
                else:
                    msg = f"Instagram HTTP {res2.status_code} - {res2.text[:120]}"
                    self.log(f"❌ Error sending to @{recipient_username}: {msg}")
                    add_reel_log(recipient_username, reel_url, "FAILED", msg)
                    return False
        except Exception as err:
            msg = f"Network Exception: {err}"
            self.log(f"❌ Error sending to @{recipient_username}: {msg}")
            add_reel_log(recipient_username, reel_url, "FAILED", msg)
            return False


    def start_automation(
        self,
        recipients: List[str],
        reel_urls: List[str],
        total_reels: int,
        start_time_str: str, # e.g. "21:00"
        end_time_str: str,   # e.g. "23:00"
        auto_discover: bool = False
    ):
        """Start automation thread with randomized timing window and optional auto Reels feed discovery."""
        if self.is_running:
            self.log("⚠️ Automation is already running!")
            return

        self.is_running = True
        self.is_paused = False
        self.status = "RUNNING"
        self.sent_count = 0
        self.failed_count = 0
        self.total_reels = total_reels

        def run_loop():
            self.log(f"🚀 Starting Reel Automation Engine...")
            self.log(f"🎯 Target Recipients: {', '.join(recipients)}")
            
            nonlocal reel_urls
            if auto_discover or not reel_urls:
                self.log("🎲 Auto Discover Feed Mode enabled! Scrolling Instagram Reels feed for fresh random Reels...")
                discovered = self.discover_random_reels_from_feed(count=self.total_reels)
                if discovered:
                    reel_urls = discovered
                    self.total_reels = len(reel_urls)
                else:
                    self.log("⚠️ No Reels discovered from feed. Falling back to default URL list.")

            self.total_reels = min(self.total_reels, len(reel_urls)) if reel_urls else self.total_reels
            self.log(f"⏱ Schedule Window: {start_time_str} to {end_time_str} ({self.total_reels} Reels)")


            # Parse start and end time objects for today (12h AM/PM or 24h)
            now = datetime.datetime.now()
            try:
                sh, sm = parse_time_str(start_time_str)
                eh, em = parse_time_str(end_time_str)
                start_dt = now.replace(hour=sh, minute=sm, second=0, microsecond=0)
                end_dt = now.replace(hour=eh, minute=em, second=0, microsecond=0)
                if end_dt <= start_dt:
                    end_dt += datetime.timedelta(days=1)
            except Exception:
                start_dt = now
                end_dt = now + datetime.timedelta(hours=2)

            # Wait if start_dt is in future
            if now < start_dt:
                wait_sec = (start_dt - now).total_seconds()
                self.log(f"⏳ Waiting {int(wait_sec)}s until scheduled start time ({start_time_str})...")
                time.sleep(min(wait_sec, 5))

            total_window_seconds = max(300, int((end_dt - datetime.datetime.now()).total_seconds()))
            avg_interval = total_window_seconds / max(1, self.total_reels)

            for i in range(self.total_reels):
                if not self.is_running:
                    self.log("⏹ Automation stopped by user.")
                    break

                while self.is_paused:
                    self.log("⏸ Automation PAUSED...")
                    time.sleep(2)

                # Select reel URL
                reel_url = reel_urls[i % len(reel_urls)] if reel_urls else "https://www.instagram.com/reels/"
                target_user = recipients[i % len(recipients)] if recipients else "target"

                # Calculate next random delay with jitter (+/- 30%)
                jitter = random.uniform(0.7, 1.3)
                current_delay = max(10, avg_interval * jitter)
                
                self.next_run_timestamp = time.time() + current_delay
                next_time_str = datetime.datetime.fromtimestamp(self.next_run_timestamp).strftime("%H:%M:%S")

                self.log(f"📤 [{i+1}/{self.total_reels}] Sending reel to @{target_user}...")
                success = self.send_direct_reel(target_user, reel_url)
                if success:
                    self.sent_count += 1
                else:
                    self.failed_count += 1

                if i < self.total_reels - 1 and self.is_running:
                    self.log(f"🕒 Next Reel scheduled at {next_time_str} (in {int(current_delay)}s)...")
                    # Sleep in small ticks to respond quickly to pause/stop signals
                    start_sleep = time.time()
                    while (time.time() - start_sleep) < current_delay:
                        if not self.is_running:
                            break
                        time.sleep(1)

            self.status = "COMPLETED"
            self.is_running = False
            self.log(f"🎉 Reel Automation Finished! Sent: {self.sent_count} | Failed: {self.failed_count}")

        self.thread = threading.Thread(target=run_loop, daemon=True)
        self.thread.start()

    def pause_automation(self):
        self.is_paused = True
        self.status = "PAUSED"
        self.log("⏸ Reel Automation PAUSED.")

    def resume_automation(self):
        self.is_paused = False
        self.status = "RUNNING"
        self.log("▶ Reel Automation RESUMED.")

    def stop_automation(self):
        self.is_running = False
        self.is_paused = False
        self.status = "STOPPED"
        self.log("⏹ Reel Automation STOPPED.")
