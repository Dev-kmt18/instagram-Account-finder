import streamlit as st
import pandas as pd
import threading
import time
import io
import os

from insta_bot.database import (
    init_db, get_counts, get_all_accounts, get_filtered_accounts,
    update_account_category, delete_account, clear_database,
    get_search_history, delete_search_history_item
)
from insta_bot.scraper import InstagramAgentEngine
from insta_bot.config import DB_PATH, EXPORTS_DIR, MIN_DELAY_PER_PROFILE, MAX_DELAY_PER_PROFILE

# Page Configuration
st.set_page_config(
    page_title="Instagram Search & Categorization Agent",
    page_icon="🤖",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom Styling
st.markdown("""
<style>
    .main-header {
        font-size: 2.2rem;
        font-weight: 700;
        background: linear-gradient(90deg, #833ab4, #fd1d1d, #fcb045);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        margin-bottom: 0.5rem;
    }
    .sub-header {
        color: #888;
        font-size: 1rem;
        margin-bottom: 1.5rem;
    }
    .metric-box {
        background-color: #1e1e2e;
        border-radius: 10px;
        padding: 15px;
        text-align: center;
        border: 1px solid #313244;
    }
    .stButton>button {
        width: 100%;
        border-radius: 8px;
        font-weight: 600;
    }
</style>
""", unsafe_allow_html=True)

# Initialize Database
init_db()

# Session State Setup
if "engine" not in st.session_state:
    st.session_state.engine = None
if "crawl_thread" not in st.session_state:
    st.session_state.crawl_thread = None
if "is_running" not in st.session_state:
    st.session_state.is_running = False
if "target_username_input" not in st.session_state:
    st.session_state.target_username_input = ""
if "keywords_input" not in st.session_state:
    st.session_state.keywords_input = "fitness, coach, trainer, gym, bodybuilder"

# Sidebar Controls
st.sidebar.markdown("## ⚙️ Agent Configuration Panel")

st.sidebar.subheader("1. Instagram Login Method")
login_method = st.sidebar.radio(
    "Select Login Mode", 
    ["Session Cookie Login (Fast & Safe ⭐️)", "Password Login"],
    index=0
)

ig_username = ""
ig_password = ""
sessionid_val = ""

# Valid active sessionid
DEFAULT_SESSIONID = "35375317586%3A7Pv50aE9LmhF9J%3A20%3AAYgWMYl9Hgo1p3811Rmia8wgIWW2KYN3t8WuEbMPPQ"

if login_method == "Session Cookie Login (Fast & Safe ⭐️)":
    sessionid_val = st.sidebar.text_input(
        "Instagram SessionID Cookie", 
        value=DEFAULT_SESSIONID,
        help="Value of 'sessionid' cookie from Chrome developer tools"
    )
    st.sidebar.success("✅ Valid Session Cookie Active")
else:
    ig_username = st.sidebar.text_input("Instagram Username", value="id_find_insta")
    ig_password = st.sidebar.text_input("Instagram Password", value="pawan@1268", type="password")

st.sidebar.subheader("2. Search Target & Parameters")
target_username = st.sidebar.text_input(
    "Target Account ID", 
    value=st.session_state.target_username_input, 
    placeholder="Enter valid username e.g. zuck or fitness_guru",
    key="target_acc_field"
)
keywords_str = st.sidebar.text_area(
    "Target Keywords (comma separated)", 
    value=st.session_state.keywords_input,
    key="keywords_field"
)
keywords_list = [k.strip() for k in keywords_str.split(",") if k.strip()]

search_mode = st.sidebar.selectbox("Search Mode", ["followers", "following", "both"])
max_limit = st.sidebar.number_input("Account Check Limit", min_value=10, max_value=10000, value=1000, step=50)
crawl_depth = st.sidebar.slider("Crawl Depth Level", min_value=1, max_value=2, value=1)

st.sidebar.subheader("3. Speed & Anti-Bot Delays")
speed_option = st.sidebar.select_slider(
    "Processing Speed",
    options=["Safe 🛡️ (4-8s)", "Standard ⚖️ (2-4s)", "Fast ⚡ (1-2.5s)"],
    value="Fast ⚡ (1-2.5s)"
)

if "Fast" in speed_option:
    min_delay_val, max_delay_val = 1.0, 2.5
elif "Standard" in speed_option:
    min_delay_val, max_delay_val = 2.0, 4.0
else:
    min_delay_val, max_delay_val = 4.0, 8.0

st.sidebar.subheader("4. Agent Commands")

col_btn1, col_btn2 = st.sidebar.columns(2)

def start_crawl(target_to_use=None, kw_to_use=None, mode_to_use=None, limit_to_use=None):
    tgt = target_to_use or target_username
    kws = kw_to_use or keywords_list
    mode = mode_to_use or search_mode
    limit = limit_to_use or max_limit

    if login_method == "Password Login" and (not ig_username or not ig_password):
        st.sidebar.error("Please enter Instagram Username & Password!")
        return
    if login_method == "Session Cookie Login (Fast & Safe ⭐️)" and not sessionid_val:
        st.sidebar.error("Please enter your Instagram sessionid cookie value!")
        return
    if not tgt:
        st.sidebar.error("Please enter Target Account Username!")
        return
    if not kws:
        st.sidebar.error("Please enter at least 1 keyword!")
        return

    engine = InstagramAgentEngine(
        username=ig_username, 
        password=ig_password, 
        sessionid=sessionid_val
    )
    st.session_state.engine = engine

    # Authenticate
    if not engine.login():
        st.sidebar.error("Failed to authenticate with Instagram. Check Live Activity Logs tab below for exact error details!")
        return

    def run_thread():
        st.session_state.is_running = True
        engine.run_crawl(
            target_username=tgt,
            keywords=kws,
            max_accounts=limit,
            mode=mode,
            max_depth=crawl_depth,
            min_delay=min_delay_val,
            max_delay=max_delay_val
        )
        st.session_state.is_running = False

    t = threading.Thread(target=run_thread, daemon=True)
    st.session_state.crawl_thread = t
    t.start()
    st.sidebar.success("Crawl agent launched successfully!")

with col_btn1:
    if st.button("▶️ Start Crawl", disabled=st.session_state.is_running):
        start_crawl()

with col_btn2:
    if st.button("⏹ Stop Agent", disabled=not st.session_state.is_running):
        if st.session_state.engine:
            st.session_state.engine.is_running = False
            st.session_state.is_running = False
            st.sidebar.warning("Stopping crawl...")

if st.sidebar.button("🗑️ Reset Database"):
    clear_database()
    st.sidebar.success("Database cleared!")
    st.rerun()

# Main Dashboard View
st.markdown('<div class="main-header">Instagram Lead Finder & Classifier Agent</div>', unsafe_allow_html=True)
st.markdown('<div class="sub-header">Search followers/following, classify accounts into Qualified (🟢), Doubtful (🟡), Unqualified (🔴), and review results.</div>', unsafe_allow_html=True)

# Metrics Section
counts = get_counts()

col_m1, col_m2, col_m3, col_m4, col_m5 = st.columns(5)

col_m1.metric("📊 Total Evaluated", counts["total"])
col_m2.metric("🟢 Qualified", counts["qualified"])
col_m3.metric("🟡 Doubtful (Review)", counts["doubtful"])
col_m4.metric("🔴 Unqualified", counts["unqualified"])
col_m5.metric("🔒 Private Profiles", counts["private"])

st.markdown("---")

# Global Filters Toolbar
st.subheader("🎯 Result Filters & Search")
col_f1, col_f2 = st.columns([1, 1])

with col_f1:
    min_match_score = st.slider(
        "Filter by Minimum Match Percentage (%)", 
        min_value=0, 
        max_value=100, 
        value=0, 
        step=5,
        help="Example: Set to 50% to show only accounts matching 50% or higher."
    )

with col_f2:
    search_query = st.text_input(
        "🔍 Quick Keyword/Bio Search Filter", 
        value="", 
        placeholder="Filter by username, full name, bio, or matched keywords..."
    )

st.markdown("---")

# Main Content Tabs
tab_qual, tab_doubt, tab_unqual, tab_all, tab_history, tab_logs = st.tabs([
    "🟢 Qualified Accounts", 
    "🟡 Doubtful Accounts (Review)", 
    "🔴 Unqualified Accounts", 
    "📊 All Data & Export", 
    "📜 Search History",
    "⚡ Live Activity Logs"
])

def make_profile_link(username):
    return f"https://www.instagram.com/{username}/"

with tab_qual:
    st.subheader("🟢 Qualified Accounts (Keywords Found)")
    qual_data = get_filtered_accounts("QUALIFIED", min_score=min_match_score, search_query=search_query)
    if qual_data:
        df_qual = pd.DataFrame(qual_data)
        df_qual["profile_url"] = df_qual["username"].apply(make_profile_link)
        display_cols = ["username", "full_name", "matched_keywords", "match_score", "bio", "is_private", "follower_count", "profile_url"]
        
        st.dataframe(
            df_qual[display_cols],
            column_config={
                "profile_url": st.column_config.LinkColumn("Instagram Link"),
                "match_score": st.column_config.ProgressColumn("Match Score", format="%d%%", min_value=0, max_value=100)
            },
            use_container_width=True
        )
        
        with st.expander("🗑️ Remove an Account from Qualified List"):
            del_user_qual = st.selectbox("Select Account to Remove", options=[""] + [a["username"] for a in qual_data], key="del_qual_select")
            if st.button("Delete Selected Account ❌", key="btn_del_qual") and del_user_qual:
                delete_account(del_user_qual)
                st.success(f"Account @{del_user_qual} removed!")
                st.rerun()
    else:
        st.info("No qualified accounts matching current filter criteria.")

with tab_doubt:
    st.subheader("🟡 Doubtful Accounts (Requires Manual Review)")
    st.caption("These accounts have partial keyword matches or ambiguous text. Review and categorize them with one click.")
    doubt_data = get_filtered_accounts("DOUBTFUL", min_score=min_match_score, search_query=search_query)
    if doubt_data:
        for acc in doubt_data:
            score_val = acc.get('match_score', 0)
            with st.expander(f"@{acc['username']} - {acc['full_name']} (Match: {acc['matched_keywords']} | Score: {score_val:.0f}%)"):
                st.write(f"**Bio:** {acc['bio'] or 'No bio text'}")
                st.write(f"**Reason:** {acc['reason']}")
                st.write(f"**Instagram Link:** https://www.instagram.com/{acc['username']}/")
                
                c1, c2, c3 = st.columns(3)
                with c1:
                    if st.button(f"Mark Qualified 🟢", key=f"qual_{acc['username']}"):
                        update_account_category(acc['username'], "QUALIFIED")
                        st.success(f"@{acc['username']} marked as QUALIFIED!")
                        st.rerun()
                with c2:
                    if st.button(f"Mark Unqualified 🔴", key=f"unqual_{acc['username']}"):
                        update_account_category(acc['username'], "UNQUALIFIED")
                        st.warning(f"@{acc['username']} marked as UNQUALIFIED!")
                        st.rerun()
                with c3:
                    if st.button(f"Remove Account 🗑️", key=f"del_{acc['username']}"):
                        delete_account(acc['username'])
                        st.info(f"@{acc['username']} deleted from database.")
                        st.rerun()
    else:
        st.info("No doubtful accounts pending review matching current filter.")

with tab_unqual:
    st.subheader("🔴 Unqualified Accounts (No Keywords)")
    unqual_data = get_filtered_accounts("UNQUALIFIED", min_score=min_match_score, search_query=search_query)
    if unqual_data:
        df_unqual = pd.DataFrame(unqual_data)
        df_unqual["profile_url"] = df_unqual["username"].apply(make_profile_link)
        display_cols = ["username", "full_name", "bio", "is_private", "profile_url"]
        st.dataframe(
            df_unqual[display_cols],
            column_config={
                "profile_url": st.column_config.LinkColumn("Instagram Link")
            },
            use_container_width=True
        )
        with st.expander("🗑️ Remove an Account from Unqualified List"):
            del_user_unqual = st.selectbox("Select Account to Remove", options=[""] + [a["username"] for a in unqual_data], key="del_unqual_select")
            if st.button("Delete Selected Account ❌", key="btn_del_unqual") and del_user_unqual:
                delete_account(del_user_unqual)
                st.success(f"Account @{del_user_unqual} removed!")
                st.rerun()
    else:
        st.info("No unqualified accounts matching current filter criteria.")

with tab_all:
    st.subheader("📊 Export & Full Database Records")
    all_data = get_filtered_accounts("ALL", min_score=min_match_score, search_query=search_query)
    if all_data:
        df_all = pd.DataFrame(all_data)
        df_all["profile_url"] = df_all["username"].apply(make_profile_link)
        
        # Download buttons
        col_ex1, col_ex2 = st.columns(2)
        
        with col_ex1:
            # Excel export
            output_excel = io.BytesIO()
            with pd.ExcelWriter(output_excel, engine="openpyxl") as writer:
                df_all.to_excel(writer, index=False, sheet_name="All Accounts")
                if counts["qualified"] > 0:
                    df_all[df_all["category"] == "QUALIFIED"].to_excel(writer, index=False, sheet_name="Qualified")
                if counts["doubtful"] > 0:
                    df_all[df_all["category"] == "DOUBTFUL"].to_excel(writer, index=False, sheet_name="Doubtful")
            
            st.download_button(
                label="📥 Export to Excel (.xlsx)",
                data=output_excel.getvalue(),
                file_name=f"insta_leads_{target_username or 'export'}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )

        with col_ex2:
            csv_data = df_all.to_csv(index=False).encode('utf-8')
            st.download_button(
                label="📥 Export to CSV (.csv)",
                data=csv_data,
                file_name=f"insta_leads_{target_username or 'export'}.csv",
                mime="text/csv"
            )

        st.dataframe(
            df_all,
            column_config={
                "profile_url": st.column_config.LinkColumn("Instagram Link"),
                "match_score": st.column_config.ProgressColumn("Match Score", format="%d%%", min_value=0, max_value=100)
            },
            use_container_width=True
        )

        with st.expander("🗑️ Delete Specific Account Record"):
            del_user_all = st.selectbox("Select Username to Remove", options=[""] + [a["username"] for a in all_data], key="del_all_select")
            if st.button("Delete Account ❌", key="btn_del_all") and del_user_all:
                delete_account(del_user_all)
                st.success(f"Account @{del_user_all} removed!")
                st.rerun()
    else:
        st.info("No data recorded in database yet matching filter criteria.")

with tab_history:
    st.subheader("📜 Target Search History & Checkpoints")
    st.caption("Review all past searches. You can resume any interrupted crawl or view its results anytime.")
    history_items = get_search_history()
    
    if history_items:
        for item in history_items:
            status_badge = (
                "🟢 COMPLETED" if item["status"] == "COMPLETED" 
                else ("🟡 RUNNING" if item["status"] == "RUNNING" 
                else "🔴 INTERRUPTED / FAILED")
            )
            with st.expander(f"Target: @{item['target_username']} | Status: {status_badge} | Date: {item['created_at']}"):
                col_h1, col_h2, col_h3 = st.columns(3)
                col_h1.write(f"**Target Username:** @{item['target_username']}")
                col_h1.write(f"**Keywords:** {item['keywords']}")
                
                col_h2.write(f"**Search Mode:** {item['search_mode']}")
                col_h2.write(f"**Account Limit:** {item['max_limit']}")
                
                col_h3.write(f"**Evaluated Count:** {item['processed_count']}")
                col_h3.write(f"**Qualified Count:** {item['qualified_count']}")

                h_btn1, h_btn2 = st.columns(2)
                with h_btn1:
                    if st.button(f"▶️ Resume / Restart Crawl for @{item['target_username']}", key=f"res_{item['id']}", disabled=st.session_state.is_running):
                        st.session_state.target_username_input = item['target_username']
                        st.session_state.keywords_input = item['keywords']
                        start_crawl(
                            target_to_use=item['target_username'],
                            kw_to_use=[k.strip() for k in item['keywords'].split(",") if k.strip()],
                            mode_to_use=item['search_mode'],
                            limit_to_use=item['max_limit']
                        )
                        st.rerun()

                with h_btn2:
                    if st.button(f"🗑️ Delete History Record", key=f"del_h_{item['id']}"):
                        delete_search_history_item(item['id'])
                        st.success("Search history item deleted!")
                        st.rerun()
    else:
        st.info("No search history recorded yet.")

with tab_logs:
    st.subheader("⚡ Live Activity Logs & Diagnostic Info")
    col_l1, col_l2 = st.columns([4, 1])
    with col_l2:
        if st.button("🧹 Clear Logs"):
            if st.session_state.engine:
                st.session_state.engine.logs = []
                st.rerun()

    if st.session_state.engine and st.session_state.engine.logs:
        st.code("\n".join(st.session_state.engine.logs[-150:]), language="text")
    else:
        st.info("Agent is idle. Start crawl to view real-time logs.")

# Non-blocking auto refresh dashboard if running
if st.session_state.is_running:
    st.markdown('<meta http-equiv="refresh" content="3">', unsafe_allow_html=True)


