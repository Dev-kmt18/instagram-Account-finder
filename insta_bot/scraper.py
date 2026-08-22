import time
import random
import os
import json
import logging
from typing import List, Dict, Optional, Callable

# Import database and classifier helpers
from insta_bot.database import (
    init_db, is_account_processed, save_account, add_to_queue,
    get_next_queue_item, mark_queue_status, get_counts, save_search_history
)
from insta_bot.classifier import evaluate_account
from insta_bot.config import (
    SESSION_FILE, MIN_DELAY_PER_PROFILE, MAX_DELAY_PER_PROFILE,
    BATCH_SIZE, COOL_DOWN_MIN_SEC, COOL_DOWN_MAX_SEC
)

# Setup logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger("InstaAgent")

class InstagramAgentEngine:
    def __init__(self, username: str = "", password: str = "", sessionid: str = ""):
        self.username = username
        self.password = password
        self.sessionid = sessionid
        self.client = None
        self.backend = None # 'instaloader'
        self.is_running = False
        self.is_paused = False
        self.logs = []
        self.min_delay = MIN_DELAY_PER_PROFILE
        self.max_delay = MAX_DELAY_PER_PROFILE
        self.max_depth = 1
        self.two_factor_required = False
        self.pending_L = None

    def log(self, message: str, level: str = "INFO"):
        msg = f"[{time.strftime('%H:%M:%S')}] {message}"
        self.logs.append(msg)
        logger.info(message)

    def _authed_session(self) -> "requests.Session":
        """Return an authenticated requests.Session using the logged-in session cookie."""
        import requests
        s = requests.Session()
        s.headers.update({
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "X-IG-App-ID": "936619743392459",
        })
        # Reuse the authenticated instaloader session cookies (sessionid etc.)
        if self.client and hasattr(self.client, "context") and hasattr(self.client.context, "_session"):
            for cookie in self.client.context._session.cookies:
                s.cookies.set(cookie.name, cookie.value, domain=cookie.domain or ".instagram.com")
        elif self.sessionid:
            s.cookies.set("sessionid", self.sessionid.strip(), domain=".instagram.com")
        return s

    def login(self) -> bool:
        """Authenticate with Instagram via Session Cookie or Credentials / 2FA."""
        self.log("Authenticating with Instagram...")
        self.two_factor_required = False
        self.pending_L = None

        import instaloader
        L = instaloader.Instaloader(
            sleep=False,
            download_pictures=False,
            download_videos=False,
            download_comments=False,
            save_metadata=False,
            compress_json=False,
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )

        # Inject essential Web App Header
        L.context._session.headers.update({
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "X-IG-App-ID": "936619743392459"
        })

        # 1. Login via Session Cookie (100% Reliable & Resilient)
        if self.sessionid and len(self.sessionid.strip()) > 5:
            try:
                self.log("Setting up sessionid cookie authentication...")
                clean_sid = self.sessionid.strip().strip('"').strip("'")
                user_id_part = clean_sid.split("%3A")[0].split(":")[0]
                
                L.context._session.cookies.clear()
                for domain in [".instagram.com", "www.instagram.com", "instagram.com"]:
                    L.context._session.cookies.set("sessionid", clean_sid, domain=domain)
                    if user_id_part and user_id_part.isdigit():
                        L.context._session.cookies.set("ds_user_id", user_id_part, domain=domain)

                # Resilient Auth Verification
                is_authed = False
                logged_user = None
                
                # Test 1: Direct Web API verification with X-IG-App-ID
                try:
                    res = L.context._session.get(
                        "https://www.instagram.com/api/v1/users/web_profile_info/?username=instagram", 
                        headers={"X-IG-App-ID": "936619743392459"},
                        timeout=10
                    )
                    if res.status_code == 200:
                        is_authed = True
                except Exception as api_e:
                    self.log(f"Note: Web API check ({api_e}), testing GraphQL...")

                # Test 2: Fallback test_login
                if not is_authed:
                    try:
                        logged_user = L.test_login()
                        if logged_user:
                            is_authed = True
                    except Exception as e:
                        self.log(f"Note: GraphQL test_login ({e})")

                if is_authed:
                    if logged_user:
                        self.username = logged_user
                        session_filename = f"session-{logged_user}"
                        L.save_session_to_file(session_filename)
                        self.log(f"🎉 Login Successful! Authenticated as @{logged_user}")
                    else:
                        self.log("🎉 Session ID Cookie Accepted & Verified!")
                    self.client = L
                    self.backend = "instaloader"
                    return True
                else:
                    self.log("❌ Provided Session ID cookie is invalid or expired.")
                    return False
            except Exception as e:
                self.log(f"❌ Cookie Auth Error: {e}")
                return False

        # 2. Check for saved native session file (if username provided)
        if self.username:
            session_filename = f"session-{self.username}"
            if os.path.exists(session_filename):
                try:
                    L.load_session_from_file(self.username, session_filename)
                    self.log(f"Restored active session from saved cache for @{self.username}!")
                    self.client = L
                    self.backend = "instaloader"
                    return True
                except Exception as e:
                    self.log(f"Saved session expired for @{self.username}, proceeding with fresh authentication...")

        # 3. Password Login (with full 2FA / OTP Verification Support)
        if self.username and self.password:
            try:
                self.log(f"Logging in with credentials for @{self.username}...")
                L.login(self.username, self.password)
                session_filename = f"session-{self.username}"
                L.save_session_to_file(session_filename)
                self.log(f"🎉 Logged in successfully as @{self.username}!")
                self.client = L
                self.backend = "instaloader"
                return True
            except instaloader.exceptions.TwoFactorAuthRequiredException:
                self.two_factor_required = True
                self.pending_L = L
                self.log("🔐 Two-Factor Authentication (OTP) Required! Please enter the 6-digit code.")
                return "2FA_REQUIRED"
            except Exception as e:
                self.log(f"❌ Password Login error for @{self.username}: {e}")
                return False

        return False

    def confirm_two_factor(self, code: str) -> bool:
        """Complete 2FA login with received OTP verification code."""
        if not self.pending_L:
            self.log("❌ No pending 2FA login session found.")
            return False
        try:
            self.log(f"Submitting 2FA OTP code for @{self.username}...")
            self.pending_L.two_factor_login(code.strip())
            session_filename = f"session-{self.username}"
            self.pending_L.save_session_to_file(session_filename)
            self.client = self.pending_L
            self.backend = "instaloader"
            self.two_factor_required = False
            self.pending_L = None
            self.log(f"🎉 2FA OTP Verified! Logged in successfully as @{self.username}!")
            return True
        except Exception as e:
            self.log(f"❌ 2FA Verification Error: {e}")
            return False

    def process_profile_node(
        self,
        node_username: str,
        node_user_id: str,
        keywords: List[str],
        depth: int,
        profile_obj: Optional[object] = None
    ) -> Optional[Dict]:
        """Fetch profile metadata without extra API calls, classify, and save to DB."""
        if is_account_processed(node_user_id, node_username):
            return None

        full_name = ""
        bio = ""
        is_private = False
        follower_count = 0
        following_count = 0

        try:
            if profile_obj:
                full_name = getattr(profile_obj, "full_name", "") or ""
                bio = getattr(profile_obj, "biography", "") or ""
                is_private = getattr(profile_obj, "is_private", False)
                follower_count = getattr(profile_obj, "followers", 0) or 0
                following_count = getattr(profile_obj, "followees", 0) or 0
            else:
                import instaloader
                prof = instaloader.Profile.from_username(self.client.context, node_username)
                full_name = prof.full_name or ""
                bio = prof.biography or ""
                is_private = prof.is_private
                follower_count = prof.followers
                following_count = prof.followees
        except Exception as e:
            # Resilient Fallback: Query Web REST API directly (authenticated)
            try:
                s = self._authed_session()
                res = s.get(f"https://www.instagram.com/api/v1/users/web_profile_info/?username={node_username}", timeout=8)
                if res.status_code == 200:
                    u = res.json().get("data", {}).get("user", {})
                    full_name = u.get("full_name", "") or ""
                    bio = u.get("biography", "") or ""
                    is_private = u.get("is_private", False)
                    follower_count = u.get("edge_followed_by", {}).get("count", 0)
                    following_count = u.get("edge_follow", {}).get("count", 0)
                else:
                    full_name = node_username
                    bio = ""
            except Exception:
                full_name = node_username
                bio = ""

        category, matched_kw, reason, match_score = evaluate_account(node_username, full_name, bio, keywords)
        
        save_account(
            user_id=str(node_user_id),
            username=node_username,
            full_name=full_name,
            bio=bio,
            is_private=is_private,
            category=category,
            matched_keywords=matched_kw,
            reason=reason,
            depth=depth,
            follower_count=follower_count,
            following_count=following_count,
            match_score=match_score
        )

        badge = "🟢 QUALIFIED" if category == "QUALIFIED" else ("🟡 DOUBTFUL" if category == "DOUBTFUL" else "🔴 UNQUALIFIED")
        priv_str = " (Private Profile)" if is_private else ""
        self.log(f"Processed @{node_username}{priv_str} -> {badge} ({match_score:.0f}%) | Matched: {matched_kw}")

        # If profile is public and within depth budget, add to queue for deeper graph crawling
        if not is_private and depth < self.max_depth:
            add_to_queue(str(node_user_id), node_username, depth + 1)

    def run_crawl(
        self,
        target_username: str,
        keywords: List[str],
        max_accounts: int = 1000,
        mode: str = "followers",
        max_depth: int = 1,
        stop_mode: str = "total",
        progress_callback: Optional[Callable[[Dict], None]] = None,
        min_delay: float = MIN_DELAY_PER_PROFILE,
        max_delay: float = MAX_DELAY_PER_PROFILE
    ):
        """Queue-driven crawl engine that extracts target's actual followers/following and classifies prospects."""
        init_db()
        self.is_running = True
        self.is_paused = False
        self.min_delay = min_delay
        self.max_delay = max_delay
        self.max_depth = max(1, int(max_depth))
        
        clean_target = target_username.strip().lstrip("@")
        stop_desc = f"{max_accounts} Qualified Leads" if stop_mode == "qualified" else f"{max_accounts} Total Accounts Checked"
        self.log(f"🚀 Launching Agent Crawl on Target: @{clean_target}")
        self.log(f"📋 Mode: {mode.upper()} | Target Goal: {stop_desc} | Keywords: {keywords}")

        # Record Search History
        initial_counts = get_counts()
        history_id = save_search_history(
            target_username=clean_target,
            keywords=keywords,
            search_mode=mode,
            max_limit=max_accounts,
            depth=max_depth,
            status="RUNNING",
            processed_count=initial_counts["total"],
            qualified_count=initial_counts["qualified"]
        )

        # Step 1: Resolve Target Profile & User ID
        target_uid = None
        target_profile = None
        try:
            import instaloader
            target_profile = instaloader.Profile.from_username(self.client.context, clean_target)
            target_uid = str(target_profile.userid)
            self.log(f"🎯 Target Loaded: @{clean_target} (ID: {target_uid}) | Followers: {target_profile.followers} | Following: {target_profile.followees}")
            add_to_queue(target_uid, clean_target, depth=1)
        except Exception as e:
            self.log(f"Target profile fetch notice: {e}. Resolving via Web API...")
            try:
                s_t = self._authed_session()
                res_t = s_t.get(f"https://www.instagram.com/api/v1/users/web_profile_info/?username={clean_target}", timeout=8)
                if res_t.status_code == 200:
                    u_t = res_t.json().get("data", {}).get("user", {})
                    target_uid = str(u_t.get("id"))
                    fol_cnt = u_t.get("edge_followed_by", {}).get("count", 0)
                    fng_cnt = u_t.get("edge_follow", {}).get("count", 0)
                    self.log(f"🎯 Target Loaded via Web API: @{clean_target} (ID: {target_uid}) | Followers: {fol_cnt} | Following: {fng_cnt}")
                    add_to_queue(target_uid, clean_target, depth=1)
                else:
                    target_uid = f"id_{clean_target}"
                    add_to_queue(target_uid, clean_target, depth=1)
            except Exception as we:
                self.log(f"Web API notice: {we}")
                target_uid = f"id_{clean_target}"
                add_to_queue(target_uid, clean_target, depth=1)

        processed_batch_count = 0

        # Helper function to check if goal is reached
        def is_goal_reached(c: Dict) -> bool:
            if stop_mode == "qualified":
                return c["qualified"] >= max_accounts
            return c["total"] >= max_accounts

        # Step 2: Continuous Crawl Loop
        while self.is_running:
            counts = get_counts()
            save_search_history(
                target_username=clean_target,
                keywords=keywords,
                search_mode=mode,
                max_limit=max_accounts,
                depth=max_depth,
                status="RUNNING",
                processed_count=counts["total"],
                qualified_count=counts["qualified"],
                history_id=history_id
            )

            if is_goal_reached(counts):
                if stop_mode == "qualified":
                    self.log(f"🎉 GOAL REACHED! Successfully found {counts['qualified']} Qualified Leads!")
                else:
                    self.log(f"🎉 GOAL REACHED! Evaluated target limit of {counts['total']} accounts!")
                break

            queue_item = get_next_queue_item()
            if not queue_item:
                self.log(f"✅ Finished scanning all accessible followers/following of target @{clean_target}.")
                break

            curr_username = queue_item["username"]
            curr_user_id = queue_item["user_id"]
            curr_depth = int(queue_item["depth"] or 1)

            # Do not walk deeper than requested crawl depth
            if curr_depth > self.max_depth:
                mark_queue_status(curr_user_id, "COMPLETED")
                continue

            self.log(f"📂 Extracting {mode.upper()} of @{curr_username} (Depth Level {curr_depth})...")

            candidates = []
            try:
                import instaloader
                profile = instaloader.Profile.from_username(self.client.context, curr_username)
                
                # Fetch actual Followers of target account
                if mode in ["followers", "both"]:
                    try:
                        self.log(f"Fetching followers list of @{curr_username}...")
                        for follower in profile.get_followers():
                            candidates.append((follower.username, str(follower.userid), follower))
                            if is_goal_reached(get_counts()) or len(candidates) >= max_accounts:
                                break
                    except Exception as fe:
                        self.log(f"Followers fetch note for @{curr_username}: {fe}")

                # Fetch actual Following of target account
                if mode in ["following", "both"] and not is_goal_reached(get_counts()):
                    try:
                        self.log(f"Fetching following list of @{curr_username}...")
                        for followee in profile.get_followees():
                            candidates.append((followee.username, str(followee.userid), followee))
                            if is_goal_reached(get_counts()) or len(candidates) >= max_accounts:
                                break
                    except Exception as fe:
                        self.log(f"Following fetch note for @{curr_username}: {fe}")
            except Exception as e:
                self.log(f"Extraction note for @{curr_username}: {e}")

            # Fallback: Try Authenticated REST API for target followers/following
            if not candidates and self.is_running:
                try:
                    s_api = self._authed_session()
                    endpoint = "followers" if mode == "followers" else "following"
                    url = f"https://www.instagram.com/api/v1/friendships/{curr_user_id}/{endpoint}/?count=50"
                    res_api = s_api.get(url, timeout=10)
                    if res_api.status_code == 200:
                        u_list = res_api.json().get("users", [])
                        self.log(f"REST API retrieved {len(u_list)} {endpoint} for @{curr_username}")
                        for u in u_list:
                            candidates.append((u.get("username"), str(u.get("pk") or u.get("id")), None))
                    elif res_api.status_code == 401 or "fail" in res_api.text:
                        self.log(f"⚠️ Instagram rate limit active. Waiting 10s before proceeding...")
                        time.sleep(10)
                except Exception as rest_e:
                    self.log(f"REST API note: {rest_e}")

            if not candidates:
                self.log(f"No more followers/following accessible for @{curr_username} (Private or restricted).")
                mark_queue_status(curr_user_id, "COMPLETED")
                continue

            self.log(f"Found {len(candidates)} candidate profiles from @{curr_username}. Evaluating metadata against keywords...")

            # Evaluate each actual follower/following node
            for uname, uid, p_obj in candidates:
                if not self.is_running:
                    break

                while self.is_paused:
                    self.log("⏸ Crawl Agent is currently PAUSED. Waiting for resume...")
                    time.sleep(1)

                if is_goal_reached(get_counts()):
                    break

                try:
                    res = self.process_profile_node(uname, uid, keywords, depth=curr_depth, profile_obj=p_obj)
                    if res:
                        processed_batch_count += 1
                        curr_counts = get_counts()
                        if progress_callback:
                            progress_callback(curr_counts)

                        # Anti-bot Random Delay
                        sleep_time = random.uniform(self.min_delay, self.max_delay)
                        self.log(f"⏳ Next check in {sleep_time:.1f}s... (Total: {curr_counts['total']} | Qualified: {curr_counts['qualified']})")
                        time.sleep(sleep_time)

                        # Batch Cool-down pause
                        if processed_batch_count % BATCH_SIZE == 0:
                            cool_down = random.uniform(COOL_DOWN_MIN_SEC, COOL_DOWN_MAX_SEC)
                            self.log(f"☕ Batch Cool-down break: waiting {cool_down:.1f} seconds to protect account...")
                            time.sleep(cool_down)
                except Exception as err:
                    self.log(f"Skipping @{uname} due to error: {err}")
                    continue

            mark_queue_status(curr_user_id, "COMPLETED")

        final_status = "COMPLETED" if is_goal_reached(get_counts()) else ("INTERRUPTED" if not self.is_running else "COMPLETED")
        self.is_running = False
        final_counts = get_counts()
        save_search_history(
            target_username=clean_target,
            keywords=keywords,
            search_mode=mode,
            max_limit=max_accounts,
            depth=max_depth,
            status=final_status,
            processed_count=final_counts["total"],
            qualified_count=final_counts["qualified"],
            history_id=history_id
        )
        self.log(f"🏁 Crawl finished ({final_status}). Total Evaluated: {final_counts['total']} | Qualified Leads: {final_counts['qualified']}")
