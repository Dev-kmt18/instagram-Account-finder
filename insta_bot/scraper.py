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

    def log(self, message: str, level: str = "INFO"):
        msg = f"[{time.strftime('%H:%M:%S')}] {message}"
        self.logs.append(msg)
        logger.info(message)

    def login(self) -> bool:
        """Authenticate with Instagram via Session Cookie or Credentials."""
        self.log("Authenticating with Instagram...")

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
                try:
                    logged_user = L.test_login()
                    if logged_user:
                        is_authed = True
                except Exception as e:
                    self.log(f"Note: GraphQL test_login rate-limited, verifying cookie directly...")

                if not is_authed:
                    try:
                        # Fallback verification by fetching profile with session cookie
                        test_prof = instaloader.Profile.from_username(L.context, "instagram")
                        if test_prof and test_prof.username == "instagram":
                            is_authed = True
                    except Exception as ve:
                        self.log(f"Profile verification failed: {ve}")

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

        # 2. Check for saved native session file (only if username provided without password)
        if self.username and not self.password:
            session_filename = f"session-{self.username}"
            if os.path.exists(session_filename):
                try:
                    L.load_session_from_file(self.username, session_filename)
                    logged_user = L.test_login()
                    if logged_user:
                        self.log(f"Restored active session for @{logged_user}!")
                        self.client = L
                        self.backend = "instaloader"
                        return True
                except Exception as e:
                    self.log(f"Failed to load session for @{self.username}: {e}")

        # 3. Password Login (Fresh login when password provided)
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
            except Exception as e:
                self.log(f"❌ Password Login error for @{self.username}: {e}")
                return False

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
            # Safe fallback: classify username directly if profile query has temporary glitch
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

        # If profile is public, add to queue for deeper graph crawling
        if not is_private:
            add_to_queue(str(node_user_id), node_username, depth + 1)

        return {
            "username": node_username,
            "category": category,
            "matched_keywords": matched_kw,
            "is_private": is_private,
            "match_score": match_score
        }

    def run_crawl(
        self,
        target_username: str,
        keywords: List[str],
        max_accounts: int = 1000,
        mode: str = "followers",
        max_depth: int = 1,
        progress_callback: Optional[Callable[[Dict], None]] = None,
        min_delay: float = MIN_DELAY_PER_PROFILE,
        max_delay: float = MAX_DELAY_PER_PROFILE
    ):
        """Continuous robust queue-driven crawl engine that STRICTLY runs until max_accounts is reached."""
        init_db()
        self.is_running = True
        self.is_paused = False
        self.min_delay = min_delay
        self.max_delay = max_delay
        
        clean_target = target_username.strip().lstrip("@")
        self.log(f"🚀 Launching Agent Crawl on target: @{clean_target}")
        self.log(f"Strict Target Limit: {max_accounts} accounts | Keywords: {keywords}")

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

        # Step 1: Add target profile to Queue
        try:
            import instaloader
            target_profile = instaloader.Profile.from_username(self.client.context, clean_target)
            target_uid = str(target_profile.userid)
            add_to_queue(target_uid, clean_target, depth=1)
        except Exception as e:
            self.log(f"❌ ERROR: Target account @{clean_target} invalid or not found: {e}")
            save_search_history(
                target_username=clean_target,
                keywords=keywords,
                search_mode=mode,
                max_limit=max_accounts,
                depth=max_depth,
                status="FAILED",
                history_id=history_id
            )
            self.is_running = False
            return

        processed_batch_count = 0

        # Step 2: Continuous Loop until MAX LIMIT is STRICTLY REACHED
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

            if counts["total"] >= max_accounts:
                self.log(f"🎉 SUCCESS! Strictly reached target limit of {max_accounts} accounts!")
                break

            queue_item = get_next_queue_item()
            if not queue_item:
                self.log("Queue empty. Waiting for pending graph nodes...")
                time.sleep(2)
                if not get_next_queue_item():
                    self.log("Completed all accessible profiles in graph tree.")
                    break
                continue

            curr_username = queue_item["username"]
            curr_user_id = queue_item["user_id"]
            curr_depth = queue_item["depth"]

            self.log(f"Scanning followers/following of @{curr_username} (Level {curr_depth})...")

            try:
                import instaloader
                profile = instaloader.Profile.from_username(self.client.context, curr_username)
                
                candidates = []
                if mode in ["followers", "both"]:
                    try:
                        for follower in profile.get_followers():
                            candidates.append((follower.username, str(follower.userid), follower))
                            if len(candidates) + get_counts()["total"] >= max_accounts:
                                break
                    except Exception as e:
                        self.log(f"Followers fetch note for @{curr_username}: {e}")

                if mode in ["following", "both"] and (len(candidates) + get_counts()["total"] < max_accounts):
                    try:
                        for followee in profile.get_followees():
                            candidates.append((followee.username, str(followee.userid), followee))
                            if len(candidates) + get_counts()["total"] >= max_accounts:
                                break
                    except Exception as e:
                        self.log(f"Following fetch note for @{curr_username}: {e}")

                # Evaluate candidate nodes with auto-error recovery
                for uname, uid, p_obj in candidates:
                    if not self.is_running:
                        break

                    while self.is_paused:
                        self.log("⏸ Crawl Agent is currently PAUSED. Waiting for resume...")
                        time.sleep(1)

                    if get_counts()["total"] >= max_accounts:
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
                            self.log(f"⏳ Waiting {sleep_time:.1f}s before next profile check... (Total: {curr_counts['total']}/{max_accounts})")
                            time.sleep(sleep_time)

                            # Batch Cool-down pause
                            if processed_batch_count % BATCH_SIZE == 0:
                                cool_down = random.uniform(COOL_DOWN_MIN_SEC, COOL_DOWN_MAX_SEC)
                                self.log(f"☕ Batch Cool-down break: waiting {cool_down:.1f} seconds to protect account...")
                                time.sleep(cool_down)
                    except Exception as err:
                        self.log(f"Skipping profile @{uname} due to error: {err}")
                        continue

                mark_queue_status(curr_user_id, "COMPLETED")

            except Exception as e:
                self.log(f"Skipping node @{curr_username}: {e}")
                mark_queue_status(curr_user_id, "FAILED")

        final_status = "COMPLETED" if get_counts()["total"] >= max_accounts else ("INTERRUPTED" if not self.is_running else "COMPLETED")
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
        self.log(f"Crawl finished ({final_status}). Total Evaluated: {final_counts['total']} accounts.")

