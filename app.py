import streamlit as st
import pandas as pd
import threading
import time
import io
import os

from insta_bot.database import (
    init_db, get_counts, get_filtered_accounts,
    update_account_category, delete_account, clear_database
)
from insta_bot.scraper import InstagramAgentEngine
from insta_bot.config import MIN_DELAY_PER_PROFILE, MAX_DELAY_PER_PROFILE

# Page Configuration
st.set_page_config(
    page_title="Instagram Lead Finder & Classifier",
    page_icon="🎯",
    layout="wide",
    initial_sidebar_state="collapsed"
)

# Initialize Database
init_db()

# Custom Styling (Pure Deep Matte Black Theme - No Blue/Shiny Tint)
st.markdown("""
<style>
    /* Pure Matte Deep Black Color Palette */
    :root {
        --bg-main: #000000;
        --card-bg: #111111;
        --border-color: #222222;
        --text-main: #ffffff;
        --text-muted: #888888;
        --accent: #6366f1;
        --accent-hover: #4f46e5;
    }
    
    body, .stApp {
        background-color: var(--bg-main) !important;
        color: var(--text-main) !important;
    }
    
    /* Header */
    .app-header {
        margin-bottom: 1.25rem;
    }
    .app-title {
        font-size: 1.6rem;
        font-weight: 700;
        color: var(--text-main);
        letter-spacing: -0.02em;
    }
    .app-subtitle {
        font-size: 0.85rem;
        color: var(--text-muted);
        margin-top: 0.2rem;
    }
    
    /* Config Labels */
    .config-header {
        font-size: 0.75rem;
        font-weight: 600;
        text-transform: uppercase;
        letter-spacing: 0.05em;
        color: var(--accent);
        margin-bottom: 0.5rem;
    }
    
    /* Status Badges */
    .badge {
        display: inline-block;
        padding: 3px 8px;
        border-radius: 4px;
        font-size: 0.75rem;
        font-weight: 600;
    }
    .badge-qualified {
        background-color: rgba(16, 185, 129, 0.15);
        color: #34d399;
        border: 1px solid rgba(16, 185, 129, 0.3);
    }
    .badge-review {
        background-color: rgba(245, 158, 11, 0.15);
        color: #fbbf24;
        border: 1px solid rgba(245, 158, 11, 0.3);
    }
    .badge-unqualified {
        background-color: rgba(107, 114, 128, 0.15);
        color: #9ca3af;
        border: 1px solid rgba(107, 114, 128, 0.3);
    }
    
    /* Keyword Chips */
    .chip-tag {
        display: inline-block;
        background-color: #222222;
        color: #e0e0e0;
        padding: 3px 10px;
        border-radius: 12px;
        font-size: 0.8rem;
        margin-right: 5px;
        margin-bottom: 5px;
        border: 1px solid #333333;
    }
    
    /* Hide Default Streamlit Sidebar */
    [data-testid="stSidebar"] {
        display: none;
    }
</style>
""", unsafe_allow_html=True)

# Session State Setup
if "engine" not in st.session_state:
    st.session_state.engine = None
if "crawl_thread" not in st.session_state:
    st.session_state.crawl_thread = None
if "is_running" not in st.session_state:
    st.session_state.is_running = False
if "kw_list" not in st.session_state:
    st.session_state.kw_list = ["fitness", "coach", "trainer", "gym"]
if "selected_usernames" not in st.session_state:
    st.session_state.selected_usernames = set()

# ---------------------------------------------------------
# 1. HEADER
# ---------------------------------------------------------
st.markdown("""
<div class="app-header">
    <div class="app-title">Instagram Lead Finder & Classifier</div>
    <div class="app-subtitle">Extract followers or following, evaluate bio metadata, and classify prospects into targeted sales leads.</div>
</div>
""", unsafe_allow_html=True)

# ---------------------------------------------------------
# 2. TOP HORIZONTAL CONFIGURATION SECTION (CLEAN ALIGNED GRID)
# ---------------------------------------------------------
with st.container():
    # Row 1: Titles
    r1_c1, r1_c2, r1_c3, r1_c4, r1_c5 = st.columns([1.2, 1.2, 1.2, 1.2, 1.4])
    r1_c1.markdown('<div class="config-header">1. Login Method</div>', unsafe_allow_html=True)
    r1_c2.markdown('<div class="config-header">2. Target Account</div>', unsafe_allow_html=True)
    r1_c3.markdown('<div class="config-header">3. Search Parameters</div>', unsafe_allow_html=True)
    r1_c4.markdown('<div class="config-header">4. Speed & Delays</div>', unsafe_allow_html=True)
    r1_c5.markdown('<div class="config-header">5. Keywords</div>', unsafe_allow_html=True)

    # Row 2: Inputs perfectly aligned on one horizontal line
    r2_c1, r2_c2, r2_c3, r2_c4, r2_c5 = st.columns([1.2, 1.2, 1.2, 1.2, 1.4])

    with r2_c1:
        login_method = st.radio(
            "Login Mode", 
            ["Session ID", "OTP / Login"], 
            horizontal=True, 
            label_visibility="collapsed"
        )
        if login_method == "Session ID":
            sessionid_val = st.text_input(
                "Session ID", 
                type="password", 
                placeholder="Paste SessionID cookie...", 
                label_visibility="collapsed"
            )
            ig_username, ig_password = "", ""
        else:
            sessionid_val = ""
            u_col1, u_col2 = st.columns(2)
            with u_col1:
                ig_username = st.text_input("Username", placeholder="User...", label_visibility="collapsed")
            with u_col2:
                ig_password = st.text_input("Password", type="password", placeholder="Pass...", label_visibility="collapsed")

    with r2_c2:
        target_username = st.text_input("Target Account ID", placeholder="e.g. zuck or handle", label_visibility="collapsed")
        search_mode = st.selectbox("Search Mode", ["followers", "following", "both"], index=0, label_visibility="collapsed")

    with r2_c3:
        max_limit = st.number_input("Check Limit", min_value=10, max_value=10000, value=1000, step=50, label_visibility="collapsed")
        crawl_depth = st.number_input("Depth", min_value=1, max_value=2, value=1, step=1, label_visibility="collapsed")

    with r2_c4:
        speed_option = st.selectbox(
            "Processing Speed / Delay",
            ["Fast ⚡ (1.0 - 2.5s)", "Standard ⚖️ (2.0 - 4.0s)", "Safe 🛡️ (4.0 - 8.0s)"],
            index=0,
            label_visibility="collapsed"
        )
        if "Fast" in speed_option:
            min_delay_val, max_delay_val = 1.0, 2.5
        elif "Standard" in speed_option:
            min_delay_val, max_delay_val = 2.0, 4.0
        else:
            min_delay_val, max_delay_val = 4.0, 8.0

    with r2_c5:
        c_kw_in, c_kw_btn = st.columns([3, 1])
        with c_kw_in:
            new_kw = st.text_input("Add Keyword", placeholder="Add & Enter...", label_visibility="collapsed")
            if new_kw and new_kw.strip():
                clean_k = new_kw.strip().lower()
                if clean_k not in st.session_state.kw_list:
                    st.session_state.kw_list.append(clean_k)
                    st.rerun()
        with c_kw_btn:
            if st.button("Clear", key="clear_kws_btn", use_container_width=True):
                st.session_state.kw_list = []
                st.rerun()

        # Render chips
        if st.session_state.kw_list:
            chips_markup = "".join([f'<span class="chip-tag">{k}</span>' for k in st.session_state.kw_list])
            st.markdown(f'<div style="margin-top:0.3rem;">{chips_markup}</div>', unsafe_allow_html=True)

st.markdown("---")

# ---------------------------------------------------------
# 3. SEARCH ACTION
# ---------------------------------------------------------
def start_crawl():
    if login_method == "OTP / Login" and (not ig_username or not ig_password):
        st.error("Please enter Instagram Username & Password!")
        return
    if login_method == "Session ID" and not sessionid_val:
        st.error("Please enter your Instagram sessionid cookie value!")
        return
    if not target_username:
        st.error("Please enter Target Account Username!")
        return
    if not st.session_state.kw_list:
        st.error("Please add at least 1 keyword!")
        return

    engine = InstagramAgentEngine(
        username=ig_username, 
        password=ig_password, 
        sessionid=sessionid_val
    )
    st.session_state.engine = engine

    # Authenticate
    if not engine.login():
        st.error("Failed to authenticate with Instagram. Check credentials or cookie!")
        return

    def run_thread():
        st.session_state.is_running = True
        engine.run_crawl(
            target_username=target_username,
            keywords=st.session_state.kw_list,
            max_accounts=max_limit,
            mode=search_mode,
            max_depth=crawl_depth,
            min_delay=min_delay_val,
            max_delay=max_delay_val
        )
        st.session_state.is_running = False

    t = threading.Thread(target=run_thread, daemon=True)
    st.session_state.crawl_thread = t
    t.start()

col_act1, col_act2, col_act3 = st.columns([1, 1, 2])
with col_act1:
    if st.button("▶️ Start Search", use_container_width=True, disabled=st.session_state.is_running, type="primary"):
        start_crawl()
with col_act2:
    if st.button("⏹ Stop Search", use_container_width=True, disabled=not st.session_state.is_running):
        if st.session_state.engine:
            st.session_state.engine.is_running = False
            st.session_state.is_running = False
            st.rerun()

st.markdown("---")

# ---------------------------------------------------------
# 4. SUMMARY METRICS
# ---------------------------------------------------------
counts = get_counts()
m1, m2, m3, m4, m5 = st.columns(5)

m1.metric("Total Evaluated", counts["total"])
m2.metric("Qualified", counts["qualified"])
m3.metric("Needs Review", counts["doubtful"])
m4.metric("Unqualified", counts["unqualified"])
m5.metric("Private Profiles", counts["private"])

st.markdown("---")

# ---------------------------------------------------------
# 5. FILTERS TOOLBAR (ALIGNED ON SAME HORIZONTAL LINE)
# ---------------------------------------------------------
st.markdown("##### Filters")
f_col1, f_col2, f_col3 = st.columns([2, 1, 1])

with f_col1:
    search_query = st.text_input("Search Filter", placeholder="Search by username, name, bio, or keyword...", label_visibility="collapsed")
with f_col2:
    min_match_score = st.number_input("Minimum Match Score (%)", min_value=0, max_value=100, value=20, step=5, label_visibility="collapsed")
with f_col3:
    category_filter_sel = st.selectbox("Category Filter", ["All Categories", "Qualified", "Needs Review", "Unqualified"], index=0, label_visibility="collapsed")

cat_db_param = None
if category_filter_sel == "Qualified":
    cat_db_param = "QUALIFIED"
elif category_filter_sel == "Needs Review":
    cat_db_param = "DOUBTFUL"
elif category_filter_sel == "Unqualified":
    cat_db_param = "UNQUALIFIED"

# Query filtered results
filtered_accounts = get_filtered_accounts(
    category_filter=cat_db_param,
    min_score=float(min_match_score),
    search_query=search_query
)

st.markdown("---")

# ---------------------------------------------------------
# 6. DIALOGS (ACCOUNT DETAILS & DELETION CONFIRMATION)
# ---------------------------------------------------------
@st.dialog("Account Details")
def show_account_details_dialog(acc):
    st.markdown(f"### @{acc['username']}")
    st.write(f"**Full Name:** {acc['full_name'] or 'N/A'}")
    
    cat = acc['category']
    if cat == "QUALIFIED":
        st.markdown("**Status:** <span class='badge badge-qualified'>Qualified</span>", unsafe_allow_html=True)
    elif cat == "DOUBTFUL":
        st.markdown("**Status:** <span class='badge badge-review'>Needs Review</span>", unsafe_allow_html=True)
    else:
        st.markdown("**Status:** <span class='badge badge-unqualified'>Unqualified</span>", unsafe_allow_html=True)

    score_val = acc.get('match_score', 0)
    st.write(f"**Match Score:** {score_val:.0f}%")
    st.write(f"**Matched Keywords:** {acc['matched_keywords'] or 'None'}")
    
    locations = []
    bio_t = (acc['bio'] or '').lower()
    uname_t = (acc['username'] or '').lower()
    name_t = (acc['full_name'] or '').lower()
    for kw in (acc['matched_keywords'] or '').split(','):
        k_clean = kw.strip().lower()
        if not k_clean: continue
        if k_clean in uname_t: locations.append("Username")
        if k_clean in name_t: locations.append("Name")
        if k_clean in bio_t: locations.append("Bio")
    
    where_matched = ", ".join(set(locations)) if locations else "Bio / Profile Text"
    st.write(f"**Where Matched:** {where_matched}")
    st.write(f"**Bio:** {acc['bio'] or 'No bio text'}")
    st.write(f"**Followers:** {acc['follower_count']:,} | **Following:** {acc['following_count']:,}")
    st.write(f"**Account Type:** {'Private Profile' if acc['is_private'] else 'Public Profile'}")
    st.write(f"**Reason:** {acc['reason']}")
    
    st.markdown("---")
    c_d1, c_d2, c_d3 = st.columns(3)
    with c_d1:
        st.link_button("Open Instagram ↗", f"https://www.instagram.com/{acc['username']}/", use_container_width=True)
    with c_d2:
        if st.button("Mark Qualified 🟢", use_container_width=True):
            update_account_category(acc['username'], "QUALIFIED")
            st.rerun()
    with c_d3:
        if st.button("Delete Account 🗑️", use_container_width=True, type="primary"):
            delete_account(acc['username'])
            st.rerun()

@st.dialog("Confirm Deletion")
def confirm_single_delete_dialog(username):
    st.write(f"Are you sure you want to delete account **@{username}**?")
    c1, c2 = st.columns(2)
    with c1:
        if st.button("Yes, Delete", type="primary", use_container_width=True):
            delete_account(username)
            st.session_state.selected_usernames.discard(username)
            st.rerun()
    with c2:
        if st.button("Cancel", use_container_width=True):
            st.rerun()

@st.dialog("Confirm Batch Deletion")
def confirm_batch_delete_dialog(usernames):
    st.write(f"Are you sure you want to delete **{len(usernames)}** selected accounts?")
    c1, c2 = st.columns(2)
    with c1:
        if st.button("Yes, Delete Selected", type="primary", use_container_width=True):
            for u in usernames:
                delete_account(u)
            st.session_state.selected_usernames.clear()
            st.rerun()
    with c2:
        if st.button("Cancel", use_container_width=True):
            st.rerun()

# ---------------------------------------------------------
# 7. RESULTS LIST UI (UNIQUE KEY SPECIFIED PER TAB TO PREVENT StreamlitDuplicateElementId)
# ---------------------------------------------------------
tab_all, tab_qual, tab_review, tab_unqual, tab_logs = st.tabs([
    "All Results",
    "Qualified",
    "Needs Review",
    "Unqualified",
    "Live Logs"
])

def render_account_list(accounts_list, tab_key="all"):
    if not accounts_list:
        st.info("No accounts matching the filter criteria.")
        return

    # Action bar for Batch Delete
    b_col1, b_col2 = st.columns([3, 1])
    with b_col2:
        num_sel = len(st.session_state.selected_usernames)
        if st.button(f"Delete Selected ({num_sel})", disabled=num_sel == 0, key=f"btn_del_sel_{tab_key}", use_container_width=True):
            confirm_batch_delete_dialog(list(st.session_state.selected_usernames))

    for acc in accounts_list:
        cat = acc["category"]
        if cat == "QUALIFIED":
            badge_html = '<span class="badge badge-qualified">Qualified</span>'
        elif cat == "DOUBTFUL":
            badge_html = '<span class="badge badge-review">Needs Review</span>'
        else:
            badge_html = '<span class="badge badge-unqualified">Unqualified</span>'

        score_val = acc.get("match_score", 0.0)
        bio_preview = (acc['bio'][:120] + "...") if acc['bio'] and len(acc['bio']) > 120 else (acc['bio'] or "No bio preview")
        
        with st.container():
            c_check, c_info, c_actions = st.columns([0.3, 4, 1.4])
            
            with c_check:
                is_selected = acc['username'] in st.session_state.selected_usernames
                chk = st.checkbox("", value=is_selected, key=f"chk_{tab_key}_{acc['username']}", label_visibility="collapsed")
                if chk:
                    st.session_state.selected_usernames.add(acc['username'])
                else:
                    st.session_state.selected_usernames.discard(acc['username'])

            with c_info:
                st.markdown(
                    f"**@{acc['username']}** &nbsp; "
                    f"<span style='color:#94a3b8;'>({acc['full_name'] or 'No Name'})</span> &nbsp; "
                    f"{badge_html} &nbsp; "
                    f"<span style='font-size:0.8rem; color:#6366f1; font-weight:600;'>Match: {score_val:.0f}%</span>", 
                    unsafe_allow_html=True
                )
                st.caption(f"Bio: {bio_preview} | Followers: {acc['follower_count']:,} | Matched: {acc['matched_keywords'] or 'None'}")

            with c_actions:
                ac1, ac2 = st.columns(2)
                with ac1:
                    if st.button("Details", key=f"det_{tab_key}_{acc['username']}", use_container_width=True):
                        show_account_details_dialog(acc)
                with ac2:
                    if st.button("Delete", key=f"del_{tab_key}_{acc['username']}", use_container_width=True):
                        confirm_single_delete_dialog(acc['username'])

with tab_all:
    render_account_list(filtered_accounts, tab_key="all")

with tab_qual:
    qual_accs = [a for a in filtered_accounts if a["category"] == "QUALIFIED"]
    render_account_list(qual_accs, tab_key="qual")

with tab_review:
    review_accs = [a for a in filtered_accounts if a["category"] == "DOUBTFUL"]
    render_account_list(review_accs, tab_key="review")

with tab_unqual:
    unqual_accs = [a for a in filtered_accounts if a["category"] == "UNQUALIFIED"]
    render_account_list(unqual_accs, tab_key="unqual")

with tab_logs:
    st.markdown("##### Live Activity Logs")
    if st.session_state.engine and st.session_state.engine.logs:
        st.code("\n".join(st.session_state.engine.logs[-150:]), language="text")
    else:
        st.info("Agent is idle. Start search to view activity logs.")

# Non-blocking auto refresh dashboard if running
if st.session_state.is_running:
    st.markdown('<meta http-equiv="refresh" content="3">', unsafe_allow_html=True)


