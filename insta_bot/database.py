import sqlite3
import datetime
import os
from typing import List, Dict, Optional, Tuple
from insta_bot.config import DB_PATH

def get_connection():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    """Initialize database tables if they do not exist."""
    conn = get_connection()
    cursor = conn.cursor()
    
    # Table for storing evaluated accounts
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS accounts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT UNIQUE,
            username TEXT UNIQUE,
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
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    # Check if match_score column exists (for existing databases)
    cursor.execute("PRAGMA table_info(accounts)")
    columns = [col[1] for col in cursor.fetchall()]
    if "match_score" not in columns:
        cursor.execute("ALTER TABLE accounts ADD COLUMN match_score REAL DEFAULT 0")

    # Queue table for graph traversal
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

    conn.commit()
    conn.close()

def is_account_processed(user_id: str, username: str) -> bool:
    """Check if account is already processed in accounts table."""
    conn = get_connection()
    cursor = conn.cursor()
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
    match_score: float = 0.0
) -> bool:
    """Save or update account in database."""
    conn = get_connection()
    cursor = conn.cursor()
    keywords_str = ", ".join(matched_keywords) if isinstance(matched_keywords, list) else str(matched_keywords)
    
    try:
        cursor.execute("""
            INSERT INTO accounts (
                user_id, username, full_name, bio, is_private, 
                follower_count, following_count, category, matched_keywords, 
                reason, depth, profile_pic_url, match_score
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(username) DO UPDATE SET
                full_name = excluded.full_name,
                bio = excluded.bio,
                is_private = excluded.is_private,
                category = excluded.category,
                matched_keywords = excluded.matched_keywords,
                reason = excluded.reason,
                match_score = excluded.match_score
        """, (
            str(user_id), str(username), full_name, bio, is_private,
            follower_count, following_count, category, keywords_str,
            reason, depth, profile_pic_url, float(match_score)
        ))
        conn.commit()
        return True
    except Exception as e:
        print(f"Error saving account {username}: {e}")
        return False
    finally:
        conn.close()

def delete_account(username: str) -> bool:
    """Delete a single account from database."""
    conn = get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("DELETE FROM accounts WHERE username = ?", (username,))
        conn.commit()
        return True
    except Exception as e:
        print(f"Error deleting account {username}: {e}")
        return False
    finally:
        conn.close()

def update_account_category(username: str, new_category: str) -> bool:
    """Manually update account category (e.g., from Doubtful to Qualified)."""
    conn = get_connection()
    cursor = conn.cursor()
    try:
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
    """Save or update search history item."""
    conn = get_connection()
    cursor = conn.cursor()
    kw_str = ", ".join(keywords) if isinstance(keywords, list) else str(keywords)
    
    if history_id:
        cursor.execute("""
            UPDATE search_history 
            SET status = ?, processed_count = ?, qualified_count = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
        """, (status, processed_count, qualified_count, history_id))
        rec_id = history_id
    else:
        cursor.execute("""
            INSERT INTO search_history (
                target_username, keywords, search_mode, max_limit, depth, 
                processed_count, qualified_count, status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (target_username, kw_str, search_mode, max_limit, depth, processed_count, qualified_count, status))
        rec_id = cursor.lastrowid
        
    conn.commit()
    conn.close()
    return rec_id

def get_search_history() -> List[Dict]:
    """Get list of past search targets."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM search_history ORDER BY id DESC")
    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]

def delete_search_history_item(history_id: int) -> bool:
    """Delete a search history entry."""
    conn = get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("DELETE FROM search_history WHERE id = ?", (history_id,))
        conn.commit()
        return True
    except Exception as e:
        print(f"Error deleting search history item {history_id}: {e}")
        return False
    finally:
        conn.close()

def add_to_queue(user_id: str, username: str, depth: int) -> bool:
    """Add profile to traversal queue."""
    conn = get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("""
            INSERT OR IGNORE INTO queue (user_id, username, depth, status)
            VALUES (?, ?, ?, 'PENDING')
        """, (str(user_id), str(username), depth))
        conn.commit()
        return True
    except Exception as e:
        print(f"Error adding to queue: {e}")
        return False
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

def mark_queue_status(user_id: str, status: str):
    """Mark item in queue as COMPLETED or FAILED."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        UPDATE queue SET status = ? WHERE user_id = ?
    """, (status, str(user_id)))
    conn.commit()
    conn.close()

def get_counts() -> Dict[str, int]:
    """Get summary counts of evaluated accounts."""
    conn = get_connection()
    cursor = conn.cursor()
    
    cursor.execute("SELECT COUNT(*) FROM accounts")
    total = cursor.fetchone()[0]
    
    cursor.execute("SELECT COUNT(*) FROM accounts WHERE category = 'QUALIFIED'")
    qualified = cursor.fetchone()[0]
    
    cursor.execute("SELECT COUNT(*) FROM accounts WHERE category = 'DOUBTFUL'")
    doubtful = cursor.fetchone()[0]
    
    cursor.execute("SELECT COUNT(*) FROM accounts WHERE category = 'UNQUALIFIED'")
    unqualified = cursor.fetchone()[0]
    
    cursor.execute("SELECT COUNT(*) FROM accounts WHERE is_private = 1")
    private_count = cursor.fetchone()[0]
    
    conn.close()
    return {
        "total": total,
        "qualified": qualified,
        "doubtful": doubtful,
        "unqualified": unqualified,
        "private": private_count
    }

def get_filtered_accounts(
    category_filter: Optional[str] = None, 
    min_score: float = 0.0,
    search_query: str = ""
) -> List[Dict]:
    """Get accounts list with category, match_score, and text search filtering."""
    conn = get_connection()
    cursor = conn.cursor()
    
    query = "SELECT * FROM accounts WHERE 1=1"
    params = []
    
    if category_filter and category_filter != "ALL":
        query += " AND category = ?"
        params.append(category_filter)
        
    if min_score > 0:
        query += " AND match_score >= ?"
        params.append(min_score)
        
    if search_query.strip():
        query += " AND (username LIKE ? OR full_name LIKE ? OR bio LIKE ? OR matched_keywords LIKE ?)"
        pattern = f"%{search_query.strip()}%"
        params.extend([pattern, pattern, pattern, pattern])
        
    query += " ORDER BY id DESC"
    
    cursor.execute(query, params)
    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]

def get_all_accounts(category_filter: Optional[str] = None) -> List[Dict]:
    """Get accounts list with optional category filtering."""
    return get_filtered_accounts(category_filter=category_filter, min_score=0.0)

def clear_database():
    """Clear all records from database."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM accounts")
    cursor.execute("DELETE FROM queue")
    cursor.execute("DELETE FROM crawl_state")
    cursor.execute("DELETE FROM search_history")
    conn.commit()
    conn.close()

