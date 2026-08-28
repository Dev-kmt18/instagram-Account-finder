import time
import random
import os
import json
import logging
import urllib.parse
from typing import List, Dict, Optional, Callable

from insta_bot.database import (
    init_db, is_account_processed, save_account, add_to_queue,
    get_next_queue_item, mark_queue_status, get_counts, save_search_history,
    reset_queue, get_pending_queue_count
)
from insta_bot.classifier import evaluate_account
from insta_bot.config import (
    SESSION_FILE, MIN_DELAY_PER_PROFILE, MAX_DELAY_PER_PROFILE,
    BATCH_SIZE, COOL_DOWN_MIN_SEC, COOL_DOWN_MAX_SEC
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger("InstaAgent")

USER_AGENTS = [
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2.1 Safari/605.1.15",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:123.0) Gecko/20100101 Firefox/123.0"
]

class InstagramAgentEngine:
    def __init__(self, username: str = "", password: str = "", sessionid: str = ""):
        self.username = username
        self.password = password
        self.sessionid = sessionid
        self.client = None
        self.backend = None
        self.is_running = False
        self.is_paused = False
        self.logs = []
        self.min_delay = MIN_DELAY_PER_PROFILE
        self.max_delay = MAX_DELAY_PER_PROFILE
        self.max_depth = 1
        self.two_factor_required = False
        self.pending_L = None
        self.current_user_agent = random.choice(USER_AGENTS)
        self.current_search_id = 0

    def log(self, message: str, level: str = "INFO"):
        msg = f"[{time.strftime('%H:%M:%S')}] {message}"
        self.logs.append(msg)
        # Keep logs trimmed to last 300 entries to save RAM
        if len(self.logs) > 300:
            self.logs = self.logs[-300:]
        logger.info(message)

    def _authed_session(self) -> "requests.Session":
        """Return an authenticated requests.Session with randomized User-Agent and IG headers."""
        import requests
        s = requests.Session()
        s.headers.update({
            "User-Agent": self.current_user_agent,
            "X-IG-App-ID": "936619743392459",
            "Accept-Language": "en-US,en;q=0.9",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Site": "same-origin"
        })
        
        if self.client and hasattr(self.client, "context") and hasattr(self.client.context, "_session"):
            for cookie in self.client.context._session.cookies:
                s.cookies.set(cookie.name, cookie.value, domain=cookie.domain or ".instagram.com")
        elif self.sessionid:
            clean_sid = urllib.parse.unquote(self.sessionid.strip().strip('"').strip("'"))
            user_id_part = clean_sid.split("%3A")[0].split(":")[0]
            for domain in [".instagram.com", "www.instagram.com", "instagram.com"]:
                s.cookies.set("sessionid", clean_sid, domain=domain)
                if user_id_part and user_id_part.isdigit():
                    s.cookies.set("ds_user_id", user_id_part, domain=domain)
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
            user_agent=self.current_user_agent
        )

        L.context._session.headers.update({
            "User-Agent": self.current_user_agent,
            "X-IG-App-ID": "936619743392459"
        })

        # 1. Login via Session Cookie
        if self.sessionid and len(self.sessionid.strip()) > 5:
            try:
                self.log("Verifying Session ID cookie with Instagram...")
                clean_sid = urllib.parse.unquote(self.sessionid.strip().strip('"').strip("'"))
                user_id_part = clean_sid.split("%3A")[0].split(":")[0]
                
                L.context._session.cookies.clear()
                for domain in [".instagram.com", "www.instagram.com", "instagram.com"]:
                    L.context._session.cookies.set("sessionid", clean_sid, domain=domain)
                    if user_id_part and user_id_part.isdigit():
                        L.context._session.cookies.set("ds_user_id", user_id_part, domain=domain)

                real_user = None
                if user_id_part and user_id_part.isdigit():
                    try:
                        prof = instaloader.Profile.from_id(L.context, int(user_id_part))
                        real_user = prof.username
                    except Exception:
                        pass

                if not real_user:
                    try:
                        test_u = L.test_login()
                        if test_u:
                            real_user = test_u
                    except Exception:
                        pass

                if real_user:
                    self.username = real_user
                    self.client = L
                    self.backend = "instaloader"
                    self.log(f"Session Cookie Verified! Connected as @{self.username}")
                    return True
                elif user_id_part and user_id_part.isdigit():
                    self.username = f"id_{user_id_part}"
                    self.client = L
                    self.backend = "instaloader"
                    self.log(f"Session Cookie Accepted for User ID: {user_id_part}")
                    return True
                else:
                    self.log("Authentication Failed: Session Cookie invalid or expired.")
                    return False
            except Exception as e:
                self.log(f"Session Cookie Verification Error: {e}")
                return False

        # 2. Check for saved native session file
        if self.username:
            session_filename = f"session-{self.username}"
            if os.path.exists(session_filename):
                try:
                    L.load_session_from_file(self.username, session_filename)
                    self.log(f"Restored active cached session for @{self.username}!")
                    self.client = L
                    self.backend = "instaloader"
                    return True
                except Exception:
                    self.log(f"Cached session expired for @{self.username}, logging in afresh...")

        # 3. Password Login with 2FA / OTP Support
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
                self.log("🔐 Two-Factor Authentication (OTP) Required! Enter 6-digit code.")
                return "2FA_REQUIRED"
            except instaloader.exceptions.BadCredentialsException:
                self.log(f"❌ Password Login Error: Wrong password or username for @{self.username}")
                return False
            except Exception as e:
                err_str = str(e)
                if "checkpoint" in err_str.lower() or "challenge" in err_str.lower():
                    self.log(f"⚠️ Instagram Checkpoint Triggered for @{self.username}: Please use Session ID login (recommended).")
                else:
                    self.log(f"❌ Password Login error for @{self.username}: {err_str}")
                return False

        return False

    def confirm_two_factor(self, code: str) -> bool:
        """Complete 2FA login with received OTP code."""
        if not self.pending_L:
            self.log("❌ No pending 2FA session found.")
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
            self.log(f"🎉 2FA OTP Verified! Logged in as @{self.username}!")
            return True
        except Exception as e:
            self.log(f"❌ 2FA Verification Error: {e}")
            return False

    def process_profile_node(
        self,
        node_username: str,
        node_user_id: str,
        keywords: List[str],
        negative_keywords: List[str],
        match_logic: str,
        depth: int,
        min_followers: int = 0,
        max_followers: int = 0,
        include_private: bool = True,
        profile_obj: Optional[object] = None
    ) -> Optional[Dict]:
        """Fetch profile metadata, parse contacts, apply quality filters, classify & save."""
        if is_account_processed(node_user_id, node_username, search_id=self.current_search_id):
            if depth < self.max_depth:
                add_to_queue(str(node_user_id), node_username, depth + 1)
            return None

        full_name = ""
        bio = ""
        is_private = False
        follower_count = 0
        following_count = 0

        # Method 1: Profile object passed from instaloader iteration
        if profile_obj and hasattr(profile_obj, "biography"):
            try:
                full_name = getattr(profile_obj, "full_name", "") or ""
                bio = getattr(profile_obj, "biography", "") or ""
                is_private = getattr(profile_obj, "is_private", False)
                follower_count = getattr(profile_obj, "followers", 0) or 0
                following_count = getattr(profile_obj, "followees", 0) or 0
            except Exception:
                pass

        # Method 2: Direct authenticated Web API call
        if not bio and not full_name:
            try:
                s = self._authed_session()
                res = s.get(f"https://www.instagram.com/api/v1/users/web_profile_info/?username={node_username}", timeout=8)
                if res.status_code == 200:
                    u = res.json().get("data", {}).get("user", {})
                    full_name = u.get("full_name", "") or ""
                    bio = u.get("biography", "") or ""
                    is_private = u.get("is_private", False)
                    follower_count = u.get("edge_followed_by", {}).get("count", 0) or 0
                    following_count = u.get("edge_follow", {}).get("count", 0) or 0
                elif res.status_code == 401 or res.status_code == 403:
                    self.log("⚠️ Session ID cookie expired or unauthorized. Re-login recommended.")
                else:
                    full_name = node_username
            except Exception:
                full_name = node_username

        # Quality Filters Check (Followers & Private state)
        if not include_private and is_private:
            self.log(f"⏩ Skipping @{node_username}: Private profile (Quality filter enabled)")
            save_account(
                user_id=str(node_user_id), username=node_username, full_name=full_name,
                bio=bio, is_private=is_private, category="UNQUALIFIED", matched_keywords=[],
                reason="Filtered out: Private Profile", depth=depth, follower_count=follower_count,
                following_count=following_count, match_score=0.0, search_id=self.current_search_id
            )
            return None

        if min_followers > 0 and follower_count < min_followers:
            self.log(f"⏩ Skipping @{node_username}: Followers ({follower_count}) below minimum threshold ({min_followers})")
            save_account(
                user_id=str(node_user_id), username=node_username, full_name=full_name,
                bio=bio, is_private=is_private, category="UNQUALIFIED", matched_keywords=[],
                reason=f"Filtered out: Followers < {min_followers}", depth=depth, follower_count=follower_count,
                following_count=following_count, match_score=0.0, search_id=self.current_search_id
            )
            return None

        if max_followers > 0 and follower_count > max_followers:
            self.log(f"⏩ Skipping @{node_username}: Followers ({follower_count}) exceed maximum threshold ({max_followers})")
            save_account(
                user_id=str(node_user_id), username=node_username, full_name=full_name,
                bio=bio, is_private=is_private, category="UNQUALIFIED", matched_keywords=[],
                reason=f"Filtered out: Followers > {max_followers}", depth=depth, follower_count=follower_count,
                following_count=following_count, match_score=0.0, search_id=self.current_search_id
            )
            return None

        # Perform Classification & Contact Extraction
        category, matched_kw, reason, match_score, email, phone = evaluate_account(
            username=node_username,
            full_name=full_name,
            bio=bio,
            keywords=keywords,
            negative_keywords=negative_keywords,
            match_logic=match_logic
        )
        
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
            match_score=match_score,
            email=email,
            phone=phone,
            search_id=self.current_search_id
        )

        badge = "🟢 QUALIFIED" if category == "QUALIFIED" else ("🟡 DOUBTFUL" if category == "DOUBTFUL" else "🔴 UNQUALIFIED")
        priv_str = " (Private)" if is_private else ""
        contact_str = f" | Contacts: {email or phone}" if (email or phone) else ""
        self.log(f"Processed @{node_username}{priv_str} -> {badge} ({match_score:.0f}%){contact_str} | Matched: {matched_kw}")

        # Add to queue if public and within depth budget
        if not is_private and depth < self.max_depth:
            add_to_queue(str(node_user_id), node_username, depth + 1)

        return {
            "user_id": str(node_user_id),
            "username": node_username,
            "full_name": full_name,
            "bio": bio,
            "is_private": is_private,
            "category": category,
            "matched_keywords": matched_kw,
            "reason": reason,
            "depth": depth,
            "follower_count": follower_count,
            "following_count": following_count,
            "match_score": match_score,
            "email": email,
            "phone": phone
        }

    def run_crawl(
        self,
        target_username: str,
        keywords: List[str],
        negative_keywords: Optional[List[str]] = None,
        max_accounts: int = 1000,
        mode: str = "followers",
        max_depth: int = 1,
        stop_mode: str = "total",
        match_logic: str = "OR",
        min_followers: int = 0,
        max_followers: int = 0,
        include_private: bool = True,
        resume_session: bool = False,
        progress_callback: Optional[Callable[[Dict], None]] = None,
        min_delay: float = MIN_DELAY_PER_PROFILE,
        max_delay: float = MAX_DELAY_PER_PROFILE
    ):
        """Queue-driven crawl engine with rate-limit backoff, quality filters & resume capability."""
        init_db()
        negative_keywords = negative_keywords or []
        self.is_running = True
        self.is_paused = False
        self.min_delay = min_delay
        self.max_delay = max_delay
        self.max_depth = max(1, int(max_depth))
        
        clean_target = target_username.strip().lstrip("@")

        if not resume_session or get_pending_queue_count() == 0:
            reset_queue()
            self.log(f"🚀 Launching Agent Crawl on Target: @{clean_target}")
        else:
            self.log(f"🔄 Resuming Cached Crawl Session ({get_pending_queue_count()} items pending in queue)...")

        stop_desc = f"{max_accounts} Qualified Leads" if stop_mode == "qualified" else f"{max_accounts} Total Accounts Checked"
        self.log(f"📋 Mode: {mode.upper()} | Goal: {stop_desc} | Keywords: {keywords} | Exclude: {negative_keywords}")

        # Record Search History
        history_id = save_search_history(
            target_username=clean_target,
            keywords=keywords,
            search_mode=mode,
            max_limit=max_accounts,
            depth=max_depth,
            status="RUNNING",
            processed_count=0,
            qualified_count=0
        )
        self.current_search_id = history_id

        # Resolve Target User ID if starting fresh
        if not resume_session or get_pending_queue_count() == 0:
            target_uid = None
            s_t = self._authed_session()
            try:
                res_t = s_t.get(f"https://www.instagram.com/api/v1/users/web_profile_info/?username={clean_target}", timeout=10)
                if res_t.status_code == 200:
                    u_t = res_t.json().get("data", {}).get("user", {})
                    target_uid = str(u_t.get("id"))
                    fol_cnt = u_t.get("edge_followed_by", {}).get("count", 0)
                    fng_cnt = u_t.get("edge_follow", {}).get("count", 0)
                    self.log(f"🎯 Target Loaded: @{clean_target} (ID: {target_uid}) | Followers: {fol_cnt:,} | Following: {fng_cnt:,}")
            except Exception as e_web:
                self.log(f"Web profile note: {e_web}")

            if not target_uid:
                try:
                    import instaloader
                    target_profile = instaloader.Profile.from_username(self.client.context, clean_target)
                    target_uid = str(target_profile.userid)
                    self.log(f"🎯 Target Loaded via Instaloader: @{clean_target} (ID: {target_uid})")
                except Exception as e_il:
                    self.log(f"Could not resolve numeric ID for @{clean_target}: {e_il}")
                    target_uid = f"id_{clean_target}"

            add_to_queue(target_uid, clean_target, depth=1)

        processed_batch_count = 0

        def is_goal_reached(c: Dict) -> bool:
            if stop_mode == "qualified":
                return c["qualified"] >= max_accounts
            return c["total"] >= max_accounts

        # Continuous Crawl Loop
        while self.is_running:
            counts = get_counts(search_id=self.current_search_id)
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
                    self.log(f"🎉 GOAL REACHED! Found {counts['qualified']} Qualified Leads!")
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

            if curr_depth > self.max_depth:
                mark_queue_status(curr_user_id, "COMPLETED")
                continue

            self.log(f"📂 Extracting {mode.upper()} of @{curr_username} (Level {curr_depth})...")

            candidates = []
            s_api = self._authed_session()

            # 1. Fetch Followers via REST API with rate-limit handling
            if mode in ["followers", "both"] and not is_goal_reached(get_counts()):
                max_id = None
                rate_limit_hits = 0
                while self.is_running and len(candidates) < max_accounts:
                    try:
                        url_f = f"https://www.instagram.com/api/v1/friendships/{curr_user_id}/followers/?count=50"
                        if max_id:
                            url_f += f"&max_id={max_id}"
                        r_f = s_api.get(url_f, timeout=10)
                        if r_f.status_code == 200:
                            f_data = r_f.json()
                            u_list = f_data.get("users", [])
                            for u in u_list:
                                candidates.append((u.get("username"), str(u.get("pk") or u.get("id")), None))
                            self.log(f"✅ Extracted {len(u_list)} followers (Total: {len(candidates)})")
                            next_max_id = f_data.get("next_max_id")
                            if not next_max_id or not u_list:
                                break
                            max_id = next_max_id
                        elif r_f.status_code in [429, 401]:
                            rate_limit_hits += 1
                            cool = rate_limit_hits * 10
                            self.log(f"⚠️ Instagram Rate Limit (HTTP {r_f.status_code}). Cooling down for {cool}s...")
                            time.sleep(cool)
                            if rate_limit_hits >= 2:
                                break
                        else:
                            break
                    except Exception as ef:
                        self.log(f"Followers fetch note: {ef}")
                        break

            # 2. Fetch Following via REST API with rate-limit handling
            if mode in ["following", "both"] and not is_goal_reached(get_counts()):
                max_id = None
                rate_limit_hits = 0
                while self.is_running and len(candidates) < max_accounts:
                    try:
                        url_fg = f"https://www.instagram.com/api/v1/friendships/{curr_user_id}/following/?count=50"
                        if max_id:
                            url_fg += f"&max_id={max_id}"
                        r_fg = s_api.get(url_fg, timeout=10)
                        if r_fg.status_code == 200:
                            fg_data = r_fg.json()
                            u_list = fg_data.get("users", [])
                            for u in u_list:
                                candidates.append((u.get("username"), str(u.get("pk") or u.get("id")), None))
                            self.log(f"✅ Extracted {len(u_list)} following (Total: {len(candidates)})")
                            next_max_id = fg_data.get("next_max_id")
                            if not next_max_id or not u_list:
                                break
                            max_id = next_max_id
                        elif r_fg.status_code in [429, 401]:
                            rate_limit_hits += 1
                            cool = rate_limit_hits * 10
                            self.log(f"⚠️ Instagram Rate Limit (HTTP {r_fg.status_code}). Cooling down for {cool}s...")
                            time.sleep(cool)
                            if rate_limit_hits >= 2:
                                break
                        else:
                            break
                    except Exception as efg:
                        self.log(f"Following fetch note: {efg}")
                        break

            # 3. Fallback to Instaloader GraphQL
            if not candidates and self.is_running:
                try:
                    import instaloader
                    profile = instaloader.Profile.from_username(self.client.context, curr_username)
                    if mode in ["followers", "both"]:
                        for follower in profile.get_followers():
                            candidates.append((follower.username, str(follower.userid), follower))
                            if len(candidates) >= max_accounts: break
                    if mode in ["following", "both"]:
                        for followee in profile.get_followees():
                            candidates.append((followee.username, str(followee.userid), followee))
                            if len(candidates) >= max_accounts: break
                except Exception as e_il:
                    self.log(f"Instaloader fallback note: {e_il}")

            if not candidates:
                self.log(f"No accessible profiles for @{curr_username} (Private or restricted).")
                mark_queue_status(curr_user_id, "COMPLETED")
                continue

            self.log(f"Evaluating {len(candidates)} candidate profiles from @{curr_username}...")

            for uname, uid, p_obj in candidates:
                if not self.is_running:
                    break

                while self.is_paused:
                    self.log("⏸ Crawl Agent PAUSED. Waiting for user resume...")
                    time.sleep(1)

                if is_goal_reached(get_counts()):
                    break

                try:
                    res = self.process_profile_node(
                        node_username=uname,
                        node_user_id=uid,
                        keywords=keywords,
                        negative_keywords=negative_keywords,
                        match_logic=match_logic,
                        depth=curr_depth,
                        min_followers=min_followers,
                        max_followers=max_followers,
                        include_private=include_private,
                        profile_obj=p_obj
                    )
                    if res:
                        processed_batch_count += 1
                        curr_counts = get_counts()
                        if progress_callback:
                            progress_callback(curr_counts)

                        # Anti-bot Delay
                        sleep_time = random.uniform(self.min_delay, self.max_delay)
                        time.sleep(sleep_time)

                        # Batch Cool-down pause
                        if processed_batch_count % BATCH_SIZE == 0:
                            cool_down = random.uniform(COOL_DOWN_MIN_SEC, COOL_DOWN_MAX_SEC)
                            self.log(f"☕ Batch Cool-down pause: waiting {cool_down:.1f}s to protect account...")
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
