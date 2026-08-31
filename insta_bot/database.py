import sqlite3
import datetime
import os
import threading
from typing import List, Dict, Optional, Tuple
from insta_bot.config import DB_PATH

# Thread lock for DB writes across background crawler & Streamlit UI threads
_db_lock = threading.Lock()

def get_connection():
    """Create a thread-safe connection configured with WAL mode and timeout."""
    conn = sqlite3.connect(DB_PATH, check_same_thread=False, timeout=10.0)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA busy_timeout=5000;")
    except Exception:
        pass
    return conn

def init_db():
    """Initialize database tables and run automatic migrations if needed."""
    with _db_lock:
        conn = get_connection()
        cursor = conn.cursor()
        
        # Table for storing evaluated accounts
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS accounts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                search_id INTEGER DEFAULT 0,
                user_id TEXT,
                username TEXT,
                full_name TEXT,
                bio TEXT,
                is_private BOOLEAN,
                follower_count INTEGER DEFAULT 0,
                following_count INTEGER DEFAULT 0,
                category TEXT, -- QUALIFIED, UNQUALIFIED, DOUBTFUL
                matched_keywords TEXT,
                reason TEXT,
                depth INTEGER DEFAULT 1,
                profile_pic_url TEXT,
                manual_override BOOLEAN DEFAULT 0,
                match_score REAL DEFAULT 0,
                email TEXT DEFAULT '',
                phone TEXT DEFAULT '',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # Auto-migration checks for existing databases
        cursor.execute("PRAGMA table_info(accounts)")
        columns = [col[1] for col in cursor.fetchall()]
        if "search_id" not in columns:
            cursor.execute("ALTER TABLE accounts ADD COLUMN search_id INTEGER DEFAULT 0")
        if "match_score" not in columns:
            cursor.execute("ALTER TABLE accounts ADD COLUMN match_score REAL DEFAULT 0")
        if "email" not in columns:
            cursor.execute("ALTER TABLE accounts ADD COLUMN email TEXT DEFAULT ''")
        if "phone" not in columns:
            cursor.execute("ALTER TABLE accounts ADD COLUMN phone TEXT DEFAULT ''")

        # Queue table for graph traversal & session resume
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS queue (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT UNIQUE,
                username TEXT,
                depth INTEGER DEFAULT 1,
                status TEXT DEFAULT 'PENDING', -- PENDING, COMPLETED, FAILED
                added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # Crawl state tracking table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS crawl_state (
                key TEXT PRIMARY KEY,
                value TEXT
            )
        """)
        
        # Search history log table for memory & tracking
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS search_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                target_username TEXT,
                keywords TEXT,
                search_mode TEXT,
                max_limit INTEGER,
                depth INTEGER,
                processed_count INTEGER DEFAULT 0,
                qualified_count INTEGER DEFAULT 0,
                status TEXT DEFAULT 'PENDING', -- RUNNING, COMPLETED, PAUSED, INTERRUPTED
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Reel Automation logs table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS reel_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id INTEGER DEFAULT 0,
                recipient TEXT,
                reel_url TEXT,
                status TEXT, -- SENT, FAILED, SCHEDULED
                message TEXT,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Scheduled Reel Tasks table for background daemon execution
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS scheduled_reel_tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                sessionid TEXT,
                recipients TEXT,
                reel_urls TEXT,
                total_reels INTEGER DEFAULT 15,
                start_time TEXT, -- e.g. "21:00"
                end_time TEXT,   -- e.g. "23:00"
                status TEXT DEFAULT 'SCHEDULED', -- SCHEDULED, RUNNING, COMPLETED, CANCELLED, FAILED
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        conn.commit()
        conn.close()

def is_account_processed(user_id: str, username: str, search_id: int = 0) -> bool:
    """Check if account is already processed in accounts table for a specific search_id."""
    conn = get_connection()
    cursor = conn.cursor()
    if search_id > 0:
        cursor.execute(
            "SELECT 1 FROM accounts WHERE (user_id = ? OR username = ?) AND search_id = ?", 
            (str(user_id), str(username), search_id)
        )
    else:
        cursor.execute(
            "SELECT 1 FROM accounts WHERE user_id = ? OR username = ?", 
            (str(user_id), str(username))
        )
    result = cursor.fetchone()
    conn.close()
    return result is not None

def save_account(
    user_id: str,
    username: str,
    full_name: str,
    bio: str,
    is_private: bool,
    category: str,
    matched_keywords: List[str],
    reason: str,
    depth: int = 1,
    follower_count: int = 0,
    following_count: int = 0,
    profile_pic_url: str = "",
    match_score: float = 0.0,
    email: str = "",
    phone: str = "",
    search_id: int = 0
) -> bool:
    """Save or update account in database per search_id session."""
    keywords_str = ", ".join(matched_keywords) if isinstance(matched_keywords, list) else str(matched_keywords)
    
    with _db_lock:
        conn = get_connection()
        cursor = conn.cursor()
        try:
            # Check if record exists for this search_id and username
            cursor.execute("SELECT id FROM accounts WHERE username = ? AND search_id = ?", (str(username), search_id))
            row = cursor.fetchone()
            if row:
                cursor.execute("""
                    UPDATE accounts SET
                        user_id = ?,
                        full_name = ?,
                        bio = ?,
                        is_private = ?,
                        follower_count = ?,
                        following_count = ?,
                        category = ?,
                        matched_keywords = ?,
                        reason = ?,
                        depth = ?,
                        profile_pic_url = ?,
                        match_score = ?,
                        email = ?,
                        phone = ?
                    WHERE id = ?
                """, (
                    str(user_id), full_name, bio, is_private, follower_count, following_count,
                    category, keywords_str, reason, depth, profile_pic_url, float(match_score),
                    email, phone, row[0]
                ))
            else:
                cursor.execute("""
                    INSERT INTO accounts (
                        search_id, user_id, username, full_name, bio, is_private, 
                        follower_count, following_count, category, matched_keywords, 
                        reason, depth, profile_pic_url, match_score, email, phone
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    search_id, str(user_id), str(username), full_name, bio, is_private,
                    follower_count, following_count, category, keywords_str,
                    reason, depth, profile_pic_url, float(match_score), email, phone
                ))
            conn.commit()
            return True
        except Exception as e:
            print(f"Error saving account {username}: {e}")
            return False
        finally:
            conn.close()

def delete_account(username: str, search_id: Optional[int] = None) -> bool:
    """Delete a single account from database."""
    with _db_lock:
        conn = get_connection()
        cursor = conn.cursor()
        try:
            if search_id:
                cursor.execute("DELETE FROM accounts WHERE username = ? AND search_id = ?", (username, search_id))
            else:
                cursor.execute("DELETE FROM accounts WHERE username = ?", (username,))
            conn.commit()
            return True
        except Exception as e:
            print(f"Error deleting account {username}: {e}")
            return False
        finally:
            conn.close()

def update_account_category(username: str, new_category: str, search_id: Optional[int] = None) -> bool:
    """Manually update account category (e.g., from Doubtful to Qualified)."""
    with _db_lock:
        conn = get_connection()
        cursor = conn.cursor()
        try:
            if search_id:
                cursor.execute("""
                    UPDATE accounts 
                    SET category = ?, manual_override = 1 
                    WHERE username = ? AND search_id = ?
                """, (new_category, username, search_id))
            else:
                cursor.execute("""
                    UPDATE accounts 
                    SET category = ?, manual_override = 1 
                    WHERE username = ?
                """, (new_category, username))
            conn.commit()
            return True
        except Exception as e:
            print(f"Error updating category for {username}: {e}")
            return False
        finally:
            conn.close()

def add_to_queue(user_id: str, username: str, depth: int = 1):
    """Add profile node to graph traversal queue."""
    with _db_lock:
        conn = get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute("""
                INSERT OR IGNORE INTO queue (user_id, username, depth, status)
                VALUES (?, ?, ?, 'PENDING')
            """, (str(user_id), str(username), depth))
            conn.commit()
        except Exception as e:
            print(f"Error adding to queue: {e}")
        finally:
            conn.close()

def get_next_queue_item() -> Optional[Dict]:
    """Get next pending queue item for crawling."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT * FROM queue WHERE status = 'PENDING' ORDER BY depth ASC, id ASC LIMIT 1
    """)
    row = cursor.fetchone()
    conn.close()
    if row:
        return dict(row)
    return None

def get_pending_queue_count() -> int:
    """Return count of remaining pending queue items for resuming crawling."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM queue WHERE status = 'PENDING'")
    cnt = cursor.fetchone()[0]
    conn.close()
    return cnt

def mark_queue_status(user_id: str, status: str):
    """Mark item in queue as COMPLETED or FAILED."""
    with _db_lock:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE queue SET status = ? WHERE user_id = ?
        """, (status, str(user_id)))
        conn.commit()
        conn.close()

def reset_queue():
    """Clear pending graph queue when starting fresh search."""
    with _db_lock:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM queue")
        conn.commit()
        conn.close()

def save_search_history(
    target_username: str,
    keywords: List[str],
    search_mode: str,
    max_limit: int,
    depth: int,
    status: str = "RUNNING",
    processed_count: int = 0,
    qualified_count: int = 0,
    history_id: Optional[int] = None
) -> int:
    """Record or update search parameters and status in search_history table."""
    kw_str = ", ".join(keywords) if isinstance(keywords, list) else str(keywords)
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    with _db_lock:
        conn = get_connection()
        cursor = conn.cursor()
        try:
            if history_id:
                cursor.execute("""
                    UPDATE search_history SET
                        processed_count = ?,
                        qualified_count = ?,
                        status = ?,
                        updated_at = ?
                    WHERE id = ?
                """, (processed_count, qualified_count, status, now, history_id))
                inserted_id = history_id
            else:
                cursor.execute("""
                    INSERT INTO search_history (
                        target_username, keywords, search_mode, max_limit, depth,
                        processed_count, qualified_count, status, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    target_username, kw_str, search_mode, max_limit, depth,
                    processed_count, qualified_count, status, now, now
                ))
                inserted_id = cursor.lastrowid
            conn.commit()
            return inserted_id
        except Exception as e:
            print(f"Error saving search history: {e}")
            return 0
        finally:
            conn.close()

def get_search_history() -> List[Dict]:
    """Retrieve full search history ordered by most recent."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM search_history ORDER BY id DESC")
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]

def delete_search_history_item(history_id: int):
    """Delete a single search history item."""
    with _db_lock:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM search_history WHERE id = ?", (history_id,))
        cursor.execute("DELETE FROM accounts WHERE search_id = ?", (history_id,))
        conn.commit()
        conn.close()

def get_counts(search_id: Optional[int] = None) -> Dict[str, int]:
    """Get summary counts of evaluated accounts for all or specific search_id."""
    conn = get_connection()
    cursor = conn.cursor()
    
    where_clause = ""
    params = []
    if search_id is not None and search_id > 0:
        where_clause = " WHERE search_id = ?"
        params = [search_id]

    cursor.execute(f"SELECT COUNT(*) FROM accounts{where_clause}", params)
    total = cursor.fetchone()[0]
    
    q_prefix = f"{where_clause} AND " if where_clause else " WHERE "
    
    cursor.execute(f"SELECT COUNT(*) FROM accounts{q_prefix}category = 'QUALIFIED'", params)
    qualified = cursor.fetchone()[0]
    
    cursor.execute(f"SELECT COUNT(*) FROM accounts{q_prefix}category = 'DOUBTFUL'", params)
    doubtful = cursor.fetchone()[0]
    
    cursor.execute(f"SELECT COUNT(*) FROM accounts{q_prefix}category = 'UNQUALIFIED'", params)
    unqualified = cursor.fetchone()[0]
    
    cursor.execute(f"SELECT COUNT(*) FROM accounts{q_prefix}is_private = 1", params)
    private_count = cursor.fetchone()[0]

    cursor.execute(f"SELECT COUNT(*) FROM accounts{q_prefix}(email != '' OR phone != '')", params)
    contacts_count = cursor.fetchone()[0]
    
    conn.close()
    return {
        "total": total,
        "qualified": qualified,
        "doubtful": doubtful,
        "unqualified": unqualified,
        "private": private_count,
        "contacts": contacts_count
    }

def get_filtered_accounts(
    category_filter: Optional[str] = None, 
    min_score: float = 0.0,
    search_query: str = "",
    has_contact_only: bool = False,
    max_followers: int = 0,
    privacy_filter: str = "ALL",
    search_id: Optional[int] = None
) -> List[Dict]:
    """Get accounts list with category, match_score, follower limit, privacy filter, text search, contact filtering, and search_id isolation."""
    conn = get_connection()
    cursor = conn.cursor()
    
    query = "SELECT * FROM accounts WHERE 1=1"
    params = []
    
    if search_id is not None and search_id > 0:
        query += " AND search_id = ?"
        params.append(search_id)

    if category_filter and category_filter != "ALL":
        query += " AND category = ?"
        params.append(category_filter)
        
    if min_score > 0:
        query += " AND match_score >= ?"
        params.append(min_score)

    if max_followers > 0:
        query += " AND follower_count <= ?"
        params.append(max_followers)

    if privacy_filter == "PUBLIC":
        query += " AND is_private = 0"
    elif privacy_filter == "PRIVATE":
        query += " AND is_private = 1"

    if has_contact_only:
        query += " AND (email != '' OR phone != '')"
        
    if search_query.strip():
        query += " AND (username LIKE ? OR full_name LIKE ? OR bio LIKE ? OR matched_keywords LIKE ? OR email LIKE ? OR phone LIKE ?)"
        pattern = f"%{search_query.strip()}%"
        params.extend([pattern, pattern, pattern, pattern, pattern, pattern])
        
    query += " ORDER BY id DESC"
    
    cursor.execute(query, params)
    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]

def get_all_accounts(category_filter: Optional[str] = None, search_id: Optional[int] = None) -> List[Dict]:
    """Get accounts list with optional category filtering and search_id isolation."""
    return get_filtered_accounts(category_filter=category_filter, min_score=0.0, search_id=search_id)

def clear_database():
    """Clear all records from database."""
    with _db_lock:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM accounts")
        cursor.execute("DELETE FROM queue")
        cursor.execute("DELETE FROM crawl_state")
        cursor.execute("DELETE FROM search_history")
        conn.commit()
        conn.close()

def add_reel_log(recipient: str, reel_url: str, status: str, message: str, task_id: int = 0):
    """Save a reel sending log entry to SQLite."""
    with _db_lock:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO reel_logs (task_id, recipient, reel_url, status, message)
            VALUES (?, ?, ?, ?, ?)
        """, (task_id, str(recipient), str(reel_url), str(status), str(message)))
        conn.commit()
        conn.close()

def get_reel_logs(limit: int = 100) -> List[Dict]:
    """Retrieve recent reel automation logs."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT * FROM reel_logs ORDER BY id DESC LIMIT ?
    """, (limit,))
    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]

def clear_reel_logs():
    """Clear all reel automation logs."""
    with _db_lock:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM reel_logs")
        conn.commit()
        conn.close()

def is_reel_already_sent(recipient: str, reel_url: str) -> bool:
    """Check if a Reel URL was already successfully sent to a recipient."""
    conn = get_connection()
    cursor = conn.cursor()
    clean_recip = str(recipient).strip().lstrip("@")
    clean_url = str(reel_url).strip()
    # Normalize URL path for accurate matching (e.g. /p/abc/ or /reel/abc/)
    short_code = ""
    for part in clean_url.split("/"):
        if len(part) >= 8 and not part.startswith("http") and not "instagram" in part:
            short_code = part.split("?")[0]
            break

    if short_code:
        cursor.execute("""
            SELECT COUNT(*) FROM reel_logs 
            WHERE LOWER(recipient) = LOWER(?) AND status = 'SENT' AND (reel_url LIKE ? OR reel_url = ?)
        """, (clean_recip, f"%{short_code}%", clean_url))
    else:
        cursor.execute("""
            SELECT COUNT(*) FROM reel_logs 
            WHERE LOWER(recipient) = LOWER(?) AND status = 'SENT' AND reel_url = ?
        """, (clean_recip, clean_url))
    
    count = cursor.fetchone()[0]
    conn.close()
    return count > 0


def add_scheduled_task(
    sessionid: str,
    recipients: str,
    reel_urls: str,
    total_reels: int,
    start_time: str,
    end_time: str
) -> int:
    """Save a background reel automation schedule."""
    with _db_lock:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO scheduled_reel_tasks (sessionid, recipients, reel_urls, total_reels, start_time, end_time, status)
            VALUES (?, ?, ?, ?, ?, ?, 'SCHEDULED')
        """, (sessionid, recipients, reel_urls, total_reels, start_time, end_time))
        task_id = cursor.lastrowid
        conn.commit()
        conn.close()
        return task_id

def get_pending_scheduled_tasks() -> List[Dict]:
    """Retrieve all SCHEDULED tasks awaiting background execution."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT * FROM scheduled_reel_tasks WHERE status = 'SCHEDULED' ORDER BY id ASC
    """)
    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]

def update_scheduled_task_status(task_id: int, status: str):
    """Update scheduled task status (SCHEDULED, RUNNING, COMPLETED, CANCELLED, FAILED)."""
    with _db_lock:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE scheduled_reel_tasks SET status = ? WHERE id = ?
        """, (status, task_id))
        conn.commit()
        conn.close()

def get_all_scheduled_tasks() -> List[Dict]:
    """Retrieve all background scheduled tasks."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT * FROM scheduled_reel_tasks ORDER BY id DESC
    """)
    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]

def delete_scheduled_task(task_id: int):
    """Delete a scheduled task entry."""
    with _db_lock:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM scheduled_reel_tasks WHERE id = ?", (task_id,))
        conn.commit()
        conn.close()

def clear_scheduled_tasks():
    """Clear all scheduled tasks."""
    with _db_lock:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM scheduled_reel_tasks")
        conn.commit()
        conn.close()



