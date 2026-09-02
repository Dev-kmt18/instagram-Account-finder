import streamlit as st
from streamlit_autorefresh import st_autorefresh
import pandas as pd
import threading
import time
import io
import os

from insta_bot.database import (
    init_db, get_counts, get_filtered_accounts,
    update_account_category, delete_account, clear_database,
    get_pending_queue_count, get_search_history,
    add_reel_log, get_reel_logs, clear_reel_logs,
    add_scheduled_task, get_all_scheduled_tasks, delete_scheduled_task
)
from insta_bot.scraper import InstagramAgentEngine
from insta_bot.reel_bot import ReelAutomationEngine, ensure_playwright_ready
from insta_bot.scheduler_daemon import get_daemon_instance
from insta_bot.config import MIN_DELAY_PER_PROFILE, MAX_DELAY_PER_PROFILE

# Tab Navigation Identifiers
TAB_LEADS = "Account Finder & Lead Classifier"
TAB_REELS = "Reel Automation Bot"

# Page Configuration
st.set_page_config(
    page_title="Instagram Lead Finder & Classifier",
    layout="wide",
    initial_sidebar_state="collapsed"
)

# Initialize Database (WAL mode & auto-migrations)
init_db()

# Warmup / Ensure Playwright browser binaries in background
ensure_playwright_ready()

# Custom Styling (Pure Dark Theme, Zero Gap Google Sheets Data Grid Aesthetics & Clean Enterprise UI)
st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@500;600;700&display=swap');

    :root {
        --bg-base: #050608;
        --bg-surface: #0D0E12;
        --bg-surface-elevated: #13161D;
        --bg-input: #080A0E;
        --border-subtle: rgba(255, 255, 255, 0.08);
        --border-hover: rgba(185, 28, 28, 0.5);
        --text-primary: #E2E8F0;
        --text-secondary: #94A3B8;
        --text-muted: #64748B;
        --accent: #8B0000;
        --accent-hover: #A50000;
        --accent-glow: rgba(139, 0, 0, 0.35);
    }
    
    body, .stApp {
        background-color: var(--bg-base) !important;
        color: var(--text-primary) !important;
        font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif !important;
    }

    /* Hide Sidebar */
    [data-testid="stSidebar"] {
        display: none;
    }

    /* Tabular Numbers for Stats & Monospace Text */
    .stat-value, [data-testid="stMetricValue"] {
        font-family: 'JetBrains Mono', monospace !important;
        font-variant-numeric: tabular-nums !important;
    }

    /* Header Component Styling */
    .app-header {
        margin-bottom: 1.25rem;
        padding-bottom: 0.85rem;
        border-bottom: 1px solid var(--border-subtle);
        display: flex;
        align-items: center;
        justify-content: space-between;
    }
    .app-title {
        font-size: 1.5rem;
        font-weight: 700;
        color: #F8FAFC;
        letter-spacing: -0.025em;
        text-transform: uppercase;
    }
    .app-subtitle {
        font-size: 0.82rem;
        color: var(--text-secondary);
        margin-top: 0.2rem;
    }

    /* Section Card Containers */
    .hero-card {
        background: var(--bg-surface);
        border: 1px solid var(--border-subtle);
        border-radius: 10px;
        padding: 18px;
        margin-bottom: 1.25rem;
    }

    .section-label {
        font-size: 0.72rem;
        font-weight: 700;
        text-transform: uppercase;
        letter-spacing: 0.08em;
        color: var(--text-secondary);
        margin-bottom: 0.75rem;
    }

    /* Custom Input Controls Styling */
    .stTextInput input, .stNumberInput input, .stSelectbox select {
        background-color: var(--bg-input) !important;
        color: var(--text-primary) !important;
        border: 1px solid var(--border-subtle) !important;
        border-radius: 6px !important;
        font-size: 0.88rem !important;
        transition: border-color 0.15s ease, box-shadow 0.15s ease !important;
    }
    .stTextInput input:focus, .stNumberInput input:focus, .stSelectbox select:focus {
        border-color: var(--accent-hover) !important;
        box-shadow: 0 0 0 2px var(--accent-glow) !important;
    }

    /* Enhanced Custom Selectbox & Dropdown Menu Styling */
    div[data-baseweb="select"] > div {
        background-color: var(--bg-input) !important;
        border: 1px solid var(--border-subtle) !important;
        border-radius: 6px !important;
        color: var(--text-primary) !important;
        font-size: 0.88rem !important;
    }
    div[data-baseweb="select"] > div:hover {
        border-color: var(--accent-hover) !important;
    }
    div[data-baseweb="popover"], div[data-baseweb="menu"], ul[role="listbox"] {
        background-color: #0D0E12 !important;
        border: 1px solid rgba(185, 28, 28, 0.4) !important;
        border-radius: 6px !important;
        box-shadow: 0 8px 32px rgba(0, 0, 0, 0.85) !important;
    }
    li[role="option"] {
        background-color: #0D0E12 !important;
        color: #E2E8F0 !important;
        padding: 8px 12px !important;
        font-size: 0.85rem !important;
    }
    li[role="option"]:hover, li[aria-selected="true"] {
        background-color: #8B0000 !important;
        color: #FFFFFF !important;
    }

    /* Status Badges */
    .badge {
        display: inline-flex;
        align-items: center;
        padding: 2px 7px;
        border-radius: 4px;
        font-size: 0.7rem;
        font-weight: 700;
        letter-spacing: 0.04em;
        text-transform: uppercase;
    }
    .badge-qualified {
        background-color: rgba(16, 185, 129, 0.15) !important;
        color: #10B981 !important;
        border: 1px solid rgba(16, 185, 129, 0.3) !important;
    }
    .badge-doubtful {
        background-color: rgba(245, 158, 11, 0.15) !important;
        color: #F59E0B !important;
        border: 1px solid rgba(245, 158, 11, 0.3) !important;
    }
    .badge-unqualified {
        background-color: rgba(239, 68, 68, 0.15) !important;
        color: #EF4444 !important;
        border: 1px solid rgba(239, 68, 68, 0.3) !important;
    }

    /* Complete Mobile Responsiveness & Layout Adaptability */
    @media (max-width: 768px) {
        .main .block-container {
            padding-left: 0.5rem !important;
            padding-right: 0.5rem !important;
            padding-top: 1rem !important;
        }
        [data-testid="column"], div[data-testid="column"] {
            width: 100% !important;
            flex: 1 1 100% !important;
            min-width: 100% !important;
            margin-bottom: 0.5rem !important;
        }
        .stButton button {
            width: 100% !important;
            margin-bottom: 0.4rem !important;
        }
        .stMetric {
            background: var(--bg-surface) !important;
            padding: 10px !important;
            border-radius: 8px !important;
            border: 1px solid var(--border-subtle) !important;
            margin-bottom: 0.5rem !important;
        }
        .hero-card {
            padding: 12px !important;
        }
        .app-title {
            font-size: 1.2rem !important;
        }
        [data-testid="stHorizontalBlock"] {
            flex-wrap: wrap !important;
        }
    }

    /* Mobile & Touch Screen Tooltip Icon (?) Fix */
    [data-testid="stTooltipIcon"] {
        cursor: pointer !important;
        display: inline-flex !important;
        align-items: center !important;
        justify-content: center !important;
        padding: 2px 4px !important;
    }
    div[data-baseweb="tooltip"], div[role="tooltip"], .stTooltipContent {
        z-index: 999999 !important;
        max-width: 90vw !important;
        background-color: #0D0E12 !important;
        color: #E2E8F0 !important;
        border: 1px solid var(--border-subtle) !important;
        border-radius: 6px !important;
        padding: 8px 12px !important;
        font-size: 0.8rem !important;
        word-break: break-word !important;
    }


    /* Simple Glowing Pulse Dot Indicator */
    @keyframes simplePulse {
        0% { transform: scale(0.85); opacity: 0.7; box-shadow: 0 0 0 0 rgba(239, 68, 68, 0.8); }
        50% { transform: scale(1.25); opacity: 1; box-shadow: 0 0 0 6px rgba(239, 68, 68, 0); }
        100% { transform: scale(0.85); opacity: 0.7; box-shadow: 0 0 0 0 rgba(239, 68, 68, 0); }
    }
    .simple-pulse-dot {
        display: inline-block;
        width: 10px;
        height: 10px;
        background-color: #EF4444;
        border-radius: 50%;
        animation: simplePulse 1.2s infinite ease-in-out;
    }

    .running-tag {
        background: rgba(185, 28, 28, 0.18);
        color: #FCA5A5;
        border: 1px solid rgba(185, 28, 28, 0.4);
        padding: 6px 10px;
        border-radius: 50%;
        display: inline-flex;
        align-items: center;
        justify-content: center;
    }
    .paused-tag {
        background: rgba(245, 158, 11, 0.15);
        color: #FCD34D;
        border: 1px solid rgba(245, 158, 11, 0.4);
        padding: 5px 12px;
        border-radius: 4px;
        font-size: 0.78rem;
        font-weight: 700;
        letter-spacing: 0.05em;
    }

    /* STICKY SIMPLE PULSE DOT INDICATOR (STAYS VISIBLE ON SCROLL) */
    .sticky-running-indicator {
        position: fixed;
        top: 14px;
        right: 70px;
        z-index: 99999;
        background: rgba(139, 0, 0, 0.95);
        border: 1px solid #B91C1C;
        padding: 7px 11px;
        border-radius: 50%;
        box-shadow: 0 4px 16px rgba(185, 28, 28, 0.45);
        display: flex;
        align-items: center;
        justify-content: center;
        backdrop-filter: blur(8px);
    }

    /* Unified Stat Bar */
    .stat-bar {
        background: var(--bg-surface);
        border: 1px solid var(--border-subtle);
        border-radius: 8px;
        padding: 14px 18px;
        display: grid;
        grid-template-columns: repeat(6, 1fr);
        gap: 12px;
        margin-bottom: 1.25rem;
    }
    .stat-item {
        padding-right: 12px;
        border-right: 1px solid var(--border-subtle);
    }
    .stat-item:last-child {
        border-right: none;
    }
    .stat-num {
        font-family: 'JetBrains Mono', monospace;
        font-size: 1.4rem;
        font-weight: 700;
        color: #F8FAFC;
        line-height: 1.2;
    }
    .stat-title {
        font-size: 0.7rem;
        font-weight: 700;
        text-transform: uppercase;
        letter-spacing: 0.06em;
        color: var(--text-secondary);
        margin-top: 4px;
    }

    /* Zero Vertical Gap Google Sheets Data Grid Table Styling */
    .stTabs [data-testid="stVerticalBlock"] {
        gap: 0rem !important;
    }
    
    .sheet-grid-header {
        background-color: #161B22 !important;
        border: 1px solid rgba(255, 255, 255, 0.15) !important;
        padding: 6px 10px !important;
        font-size: 0.72rem !important;
        font-weight: 700 !important;
        color: #94A3B8 !important;
        text-transform: uppercase !important;
        letter-spacing: 0.04em !important;
    }
    
    .sheet-grid-cell {
        background-color: #0A0C10 !important;
        border: 1px solid rgba(255, 255, 255, 0.07) !important;
        padding: 5px 10px !important;
        font-size: 0.82rem !important;
        color: #E2E8F0 !important;
        display: flex;
        align-items: center;
        overflow: hidden;
        white-space: nowrap;
        text-overflow: ellipsis;
        height: 38px !important;
    }
    
    /* Primary vs Ghost Buttons */
    div.stButton > button[kind="primary"] {
        background-color: var(--accent) !important;
        color: #FFFFFF !important;
        border: 1px solid var(--accent-hover) !important;
        font-weight: 600 !important;
        border-radius: 6px !important;
        box-shadow: 0 4px 12px var(--accent-glow) !important;
        transition: all 0.15s ease !important;
    }
    div.stButton > button[kind="primary"]:hover {
        background-color: var(--accent-hover) !important;
        box-shadow: 0 6px 16px rgba(185, 28, 28, 0.45) !important;
    }

    div.stButton > button[kind="secondary"] {
        background-color: var(--bg-surface-elevated) !important;
        color: var(--text-primary) !important;
        border: 1px solid var(--border-subtle) !important;
        font-weight: 500 !important;
        border-radius: 6px !important;
        transition: all 0.15s ease !important;
    }

    /* Main Navigation Segmented Control Bar */
    div[data-testid="stSegmentedControl"] {
        background-color: #0D0E12 !important;
        border: 1px solid rgba(255, 255, 255, 0.1) !important;
        border-radius: 8px !important;
        padding: 4px !important;
        margin-bottom: 1.25rem !important;
        display: inline-flex !important;
        gap: 6px !important;
    }
    div[data-testid="stSegmentedControl"] button {
        border-radius: 6px !important;
        border: none !important;
        font-family: 'Inter', sans-serif !important;
        font-size: 0.9rem !important;
        font-weight: 600 !important;
        padding: 8px 22px !important;
        color: #94A3B8 !important;
        background: transparent !important;
        transition: all 0.2s ease !important;
    }
    div[data-testid="stSegmentedControl"] button:hover {
        color: #F8FAFC !important;
        background-color: rgba(255, 255, 255, 0.06) !important;
    }
    div[data-testid="stSegmentedControl"] button[aria-checked="true"],
    div[data-testid="stSegmentedControl"] button[aria-selected="true"],
    div[data-testid="stSegmentedControl"] button[data-checked="true"] {
        background: linear-gradient(135deg, #8B0000 0%, #A50000 100%) !important;
        color: #FFFFFF !important;
        box-shadow: 0 2px 10px rgba(139, 0, 0, 0.45) !important;
    }
    div.stButton > button[kind="secondary"]:hover {
        border-color: var(--border-hover) !important;
        color: #FFFFFF !important;
    }

    .desktop-spacer {
        margin-top: 28px;
    }

    /* Mobile Responsiveness */
    @media (max-width: 768px) {
        .block-container {
            padding-top: 0.75rem !important;
            padding-bottom: 1.5rem !important;
            padding-left: 0.5rem !important;
            padding-right: 0.5rem !important;
        }
        .app-header {
            flex-direction: column !important;
            align-items: flex-start !important;
            gap: 8px !important;
        }
        .app-title {
            font-size: 1.2rem !important;
        }
        .app-subtitle {
            font-size: 0.75rem !important;
        }
        .stat-bar {
            grid-template-columns: repeat(2, 1fr) !important;
            gap: 12px 10px !important;
            padding: 12px 14px !important;
        }
        .stat-item {
            border-right: none !important;
            border-bottom: 1px solid var(--border-subtle) !important;
            padding-bottom: 8px !important;
            padding-right: 0 !important;
        }
        .stat-item:nth-last-child(-n+2) {
            border-bottom: none !important;
        }
        .stat-num {
            font-size: 1.2rem !important;
        }
        .desktop-spacer {
            margin-top: 0px !important;
        }
        .stButton button {
            width: 100% !important;
        }
        .sticky-running-indicator {
            top: 8px !important;
            right: 12px !important;
            padding: 5px 9px !important;
        }
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
if "is_paused" not in st.session_state:
    st.session_state.is_paused = False
if "is_authenticated" not in st.session_state:
    st.session_state.is_authenticated = False
if "auth_user" not in st.session_state:
    st.session_state.auth_user = ""
if "kw_list" not in st.session_state:
    st.session_state.kw_list = []
if "neg_kw_list" not in st.session_state:
    st.session_state.neg_kw_list = []
if "recent_keywords" not in st.session_state:
    st.session_state.recent_keywords = []
if "selected_usernames" not in st.session_state:
    st.session_state.selected_usernames = set()
if "awaiting_otp" not in st.session_state:
    st.session_state.awaiting_otp = False
if "selected_search_id" not in st.session_state:
    st.session_state.selected_search_id = None
if "reel_engine" not in st.session_state:
    st.session_state.reel_engine = ReelAutomationEngine()

# Synchronize state with background engine actively
thread_alive = st.session_state.crawl_thread is not None and st.session_state.crawl_thread.is_alive()
if not thread_alive:
    st.session_state.is_running = False
    if st.session_state.engine:
        st.session_state.engine.is_running = False

if st.session_state.engine and thread_alive:
    st.session_state.is_running = st.session_state.engine.is_running
    st.session_state.is_paused = st.session_state.engine.is_paused

reel_engine_active = st.session_state.reel_engine and st.session_state.reel_engine.is_running and not st.session_state.reel_engine.is_paused

# Reactivity Engine: Refresh automatically EVERY 2.5 seconds WITHOUT UI Freeze while crawling
if (st.session_state.is_running and not st.session_state.is_paused) or reel_engine_active:
    st_autorefresh(interval=2500, limit=None, key="crawl_auto_refresh")

inputs_disabled = st.session_state.is_running and not st.session_state.is_paused

# STICKY RUNNING STATUS INDICATOR WITH SIMPLE PULSE DOT (STAYS VISIBLE ON SCROLL)
if st.session_state.is_running and not st.session_state.is_paused:
    st.markdown(
        '<div class="sticky-running-indicator" title="Search Crawl Active">'
        '<span class="simple-pulse-dot"></span>'
        '</div>',
        unsafe_allow_html=True
    )

# ---------------------------------------------------------
# 1. HEADER
# ---------------------------------------------------------
status_badge_html = ""
if st.session_state.is_running and not st.session_state.is_paused:
    status_badge_html = '<span class="running-tag" title="Search Crawl Active"><span class="simple-pulse-dot"></span></span>'
elif st.session_state.is_running and st.session_state.is_paused:
    status_badge_html = '<span class="paused-tag">[AGENT PAUSED]</span>'

st.markdown(
    f'<div class="app-header">'
    f'<div>'
    f'<div class="app-title">Instagram Lead Finder & Classifier</div>'
    f'<div class="app-subtitle">Extract followers or following, evaluate bio metadata, parse contact details & classify sales leads.</div>'
    f'</div>'
    f'<div>{status_badge_html}</div>'
    f'</div>',
    unsafe_allow_html=True
)

def render_account_finder_tab():
    # ---------------------------------------------------------
    # 2. STEP 1: AUTHENTICATION
    # ---------------------------------------------------------
    if not st.session_state.is_authenticated:
        st.markdown("""
        <div style="background: var(--bg-surface); border: 1px solid var(--border-subtle); border-radius: 8px; padding: 18px; margin-bottom: 1.2rem;">
            <div style="color: #F8FAFC; font-size: 0.95rem; font-weight: 700; text-transform: uppercase; letter-spacing: 0.05em;">
                Step 1: Authenticate Instagram Account
            </div>
            <div style="color: #94A3B8; font-size: 0.82rem; margin-top: 4px;">
                Provide valid Session ID or Instagram credentials. Session ID verification fetches the actual profile name before unlocking workspace parameters.
            </div>
        </div>
        """, unsafe_allow_html=True)

        auth_col_mode, auth_col_inputs = st.columns([1.2, 3.8])

        with auth_col_mode:
            auth_mode = st.radio("Authentication Method", ["Session ID", "OTP / Login"], index=0, label_visibility="collapsed")

        with auth_col_inputs:
            if auth_mode == "Session ID":
                c_sid_in, c_sid_btn = st.columns([3, 1])
                with c_sid_in:
                    sessionid_input_val = st.text_input("Session ID", type="password", placeholder="Paste Instagram sessionid cookie value here...", label_visibility="collapsed")
                with c_sid_btn:
                    if st.button("Connect Account", type="primary", use_container_width=True):
                        if sessionid_input_val and len(sessionid_input_val.strip()) > 5:
                            with st.spinner("Validating Session ID with Instagram..."):
                                eng = InstagramAgentEngine(sessionid=sessionid_input_val)
                                if eng.login():
                                    st.session_state.engine = eng
                                    st.session_state.saved_sessionid = sessionid_input_val.strip()
                                    st.session_state.is_authenticated = True
                                    st.session_state.auth_user = eng.username or "Authenticated User"
                                    st.success(f"Connected successfully as @{st.session_state.auth_user}!")
                                    st.rerun()
                                else:
                                    st.error("Authentication failed. The Session ID cookie is invalid, expired, or rejected by Instagram. Please check your sessionid cookie and try again.")
                        else:
                            st.error("Please enter a valid sessionid cookie value.")

                with st.expander("Session ID Instructions"):
                    st.markdown("""
                    **Mobile Browser Method (Chrome / Safari / Kiwi):**
                    1. Open `https://www.instagram.com` on your phone browser and log in.
                    2. Click the **Lock Icon** next to URL bar -> **Cookies & Site Data** -> **Cookies** -> Select `sessionid` -> Copy string value.

                    **PC Method:**
                    Press `F12` in Chrome -> **Application** -> **Cookies** -> `sessionid` -> Copy value.
                    """)
            else:
                if not st.session_state.awaiting_otp:
                    c_u1, c_u2, c_u3 = st.columns([1.5, 1.5, 1])
                    with c_u1:
                        u_val = st.text_input("Username", placeholder="Instagram username...", label_visibility="collapsed")
                    with c_u2:
                        p_val = st.text_input("Password", type="password", placeholder="Instagram password...", label_visibility="collapsed")
                    with c_u3:
                        if st.button("Login Account", type="primary", use_container_width=True):
                            if u_val and p_val:
                                with st.spinner("Authenticating..."):
                                    eng = InstagramAgentEngine(username=u_val, password=p_val)
                                    st.session_state.engine = eng
                                    st.session_state.saved_username = u_val
                                    st.session_state.saved_password = p_val
                                    login_res = eng.login()
                                    if login_res == "2FA_REQUIRED" or eng.two_factor_required:
                                        st.session_state.awaiting_otp = True
                                        st.rerun()
                                    elif login_res:
                                        st.session_state.is_authenticated = True
                                        st.session_state.auth_user = eng.username or u_val
                                        st.success(f"Connected as @{st.session_state.auth_user}!")
                                        st.rerun()
                                    else:
                                        st.error("Authentication failed. Please verify your Instagram username and password or use Session ID login.")
                            else:
                                st.error("Please enter both username and password.")
                else:
                    st.markdown("""
                    <div style="background: rgba(139, 0, 0, 0.15); border: 1px solid #8B0000; border-radius: 6px; padding: 10px 14px; margin-bottom: 0.8rem;">
                        <span style="color: #FCA5A5; font-weight: 600; font-size: 0.88rem;">Two-Factor Authentication (OTP) Required</span>
                        <div style="color: #CBD5E1; font-size: 0.8rem; margin-top: 2px;">Enter the 6-digit verification code sent to your mobile device or authenticator app.</div>
                    </div>
                    """, unsafe_allow_html=True)
                    otp_c1, otp_c2, otp_c3 = st.columns([2, 1, 1])
                    with otp_c1:
                        otp_val_in = st.text_input("6-Digit OTP", placeholder="Enter 6-digit code...", label_visibility="collapsed", key="otp_in_step1")
                    with otp_c2:
                        if st.button("Confirm OTP", type="primary", use_container_width=True):
                            if otp_val_in and st.session_state.engine:
                                if st.session_state.engine.confirm_two_factor(otp_val_in):
                                    st.session_state.awaiting_otp = False
                                    st.session_state.is_authenticated = True
                                    st.session_state.auth_user = st.session_state.engine.username
                                    st.success("OTP Verified & Connected!")
                                    st.rerun()
                                else:
                                    st.error("Invalid OTP code.")
                            else:
                                st.error("Please enter the 6-digit OTP code.")
                    with otp_c3:
                        if st.button("Cancel", use_container_width=True):
                            st.session_state.awaiting_otp = False
                            st.rerun()

        st.markdown("---")

    # ---------------------------------------------------------
    # 3. STEP 2: SEARCH PARAMETERS & CONTROL PANEL
    # ---------------------------------------------------------
    else:
        # Top Account Connection Status Bar
        b_col1, b_col2 = st.columns([4, 1])
        with b_col1:
            st.markdown(f"""
            <div style="background: rgba(16, 185, 129, 0.08); border: 1px solid rgba(16, 185, 129, 0.25); border-radius: 6px; padding: 8px 14px; display: flex; align-items: center; gap: 8px; margin-bottom: 0.8rem;">
                <span style="color: #10B981; font-weight: 700; font-size: 0.85rem;">CONNECTED ACCOUNT:</span>
                <span style="color: #F8FAFC; font-weight: 600; font-size: 0.85rem;">@{st.session_state.auth_user}</span>
                <span style="color: #94A3B8; font-size: 0.78rem;">— Verified & Ready</span>
            </div>
            """, unsafe_allow_html=True)
        with b_col2:
            if st.button("Disconnect", use_container_width=True, disabled=inputs_disabled):
                st.session_state.is_authenticated = False
                st.session_state.engine = None
                st.session_state.auth_user = ""
                st.rerun()

        # PRIMARY ACTION ZONE HERO CARD
        st.markdown("""
        <div style="background: var(--bg-surface); border: 1px solid var(--border-subtle); border-radius: 8px; padding: 16px 18px; margin-bottom: 1rem;">
            <div style="font-size: 0.72rem; font-weight: 700; text-transform: uppercase; letter-spacing: 0.08em; color: var(--text-secondary); margin-bottom: 10px;">
                Primary Action Zone
            </div>
        </div>
        """, unsafe_allow_html=True)

        hero_c1, hero_c2, hero_c3, hero_c4 = st.columns([1.8, 2.4, 1.2, 1.3])

        with hero_c1:
            target_username = st.text_input("Target Account Username", placeholder="e.g. instagram_username", key="target_user_field", disabled=inputs_disabled)
        with hero_c2:
            typed_kw_input = st.text_input(
                "Target Keywords (comma-separated)",
                value=", ".join(st.session_state.kw_list) if st.session_state.kw_list else "",
                placeholder="Type target keywords (e.g. mbbs, kolkata, doctor)...",
                key="kw_input_field",
                disabled=inputs_disabled
            )
        with hero_c3:
            search_mode = st.selectbox("Search Mode", ["followers", "following", "both"], index=0, disabled=inputs_disabled)
        with hero_c4:
            st.markdown("<div class='desktop-spacer'></div>", unsafe_allow_html=True)
            pending_queue_count = get_pending_queue_count()
            if not st.session_state.is_running:
                if st.button("Start Search", use_container_width=True, type="primary"):
                    final_kws = []
                    if typed_kw_input:
                        for k in typed_kw_input.split(","):
                            clean_k = k.strip().lower()
                            if clean_k and clean_k not in final_kws:
                                final_kws.append(clean_k)
                    elif st.session_state.kw_list:
                        final_kws = list(st.session_state.kw_list)

                    final_neg_kws = []
                    typed_neg_kw = st.session_state.get("neg_kw_input_field", "").strip()
                    if typed_neg_kw:
                        for k in typed_neg_kw.split(","):
                            clean_k = k.strip().lower()
                            if clean_k and clean_k not in final_neg_kws:
                                final_neg_kws.append(clean_k)
                    st.session_state.neg_kw_list = final_neg_kws

                    if not target_username and pending_queue_count == 0:
                        st.error("Please enter Target Username!")
                    elif not final_kws:
                        st.error("Please enter Target Keywords!")
                    else:
                        if not st.session_state.engine:
                            sid_saved = st.session_state.get("saved_sessionid", "")
                            u_saved = st.session_state.get("saved_username", "")
                            p_saved = st.session_state.get("saved_password", "")
                            st.session_state.engine = InstagramAgentEngine(username=u_saved, password=p_saved, sessionid=sid_saved)
                            st.session_state.engine.login()

                        engine_ref = st.session_state.engine
                        st.session_state.kw_list = final_kws
                        st.session_state.is_paused = False
                        st.session_state.is_running = True
                        st.session_state.selected_search_id = None
                        engine_ref.is_running = True
                        engine_ref.is_paused = False

                        def run_thread(eng, target_user, kws, neg_kws, max_accs, mode_s, depth, stop_m, logic, min_f, max_f, inc_priv):
                            try:
                                eng.run_crawl(
                                    target_username=target_user,
                                    keywords=kws,
                                    negative_keywords=neg_kws,
                                    max_accounts=max_accs,
                                    mode=mode_s,
                                    max_depth=depth,
                                    stop_mode=stop_m,
                                    match_logic=logic,
                                    min_followers=min_f,
                                    max_followers=max_f,
                                    include_private=inc_priv,
                                    resume_session=False
                                )
                            except Exception as thread_err:
                                if eng:
                                    eng.log(f"Crawl Error: {thread_err}")
                                    eng.is_running = False

                        val_max_limit = st.session_state.get("cfg_max_limit", 1000)
                        val_crawl_depth = st.session_state.get("cfg_crawl_depth", 1)
                        val_match_logic = "AND" if "ALL" in str(st.session_state.get("cfg_match_logic", "")) else "OR"
                        val_stop_mode = "qualified" if "Qualified" in str(st.session_state.get("cfg_stop_mode", "")) else "total"
                        val_min_f = st.session_state.get("cfg_min_followers", 0)
                        val_max_f = st.session_state.get("cfg_max_followers", 0)
                        val_inc_priv = st.session_state.get("cfg_inc_private", True)

                        t = threading.Thread(
                            target=run_thread,
                            args=(
                                engine_ref, target_username, final_kws, final_neg_kws,
                                val_max_limit, search_mode, val_crawl_depth, val_stop_mode, val_match_logic,
                                val_min_f, val_max_f, val_inc_priv
                            ),
                            daemon=True
                        )
                        st.session_state.crawl_thread = t
                        t.start()
                        st.rerun()
            else:
                if st.session_state.is_paused:
                    if st.button("Resume Search", use_container_width=True, type="primary"):
                        st.session_state.is_paused = False
                        if st.session_state.engine:
                            st.session_state.engine.is_paused = False
                        st.rerun()
                else:
                    st.button("●", use_container_width=True, disabled=True, help="Search Crawl Active")

        # ADVANCED CONFIGURATION AREA (COLLAPSIBLE TABS)
        with st.expander("Advanced Settings & Limits", expanded=True):
            tab_cfg_limits, tab_cfg_filters, tab_cfg_neg = st.tabs([
                "Limits & Depth",
                "Quality Filters",
                "Blacklist Keywords"
            ])

            with tab_cfg_limits:
                cfg_l1, cfg_l2, cfg_l3, cfg_l4 = st.columns(4)
                with cfg_l1:
                    max_limit = st.number_input("Limit Count", min_value=1, max_value=10000000, value=1000, step=100, key="cfg_max_limit", disabled=inputs_disabled, help="Set any target limit count without restriction (e.g. 5,000, 50,000, or 10,000,000)...")
                with cfg_l2:
                    stop_mode_sel = st.selectbox("Stop Goal", ["Total Scanned", "Qualified Goal"], index=0, key="cfg_stop_mode", disabled=inputs_disabled, help="Total Scanned: Stops after checking N total accounts.\nQualified Goal: Keeps searching until N Qualified Leads are found.")
                with cfg_l3:
                    crawl_depth = st.number_input("Crawl Depth", min_value=1, max_value=2, value=1, step=1, key="cfg_crawl_depth", disabled=inputs_disabled, help="Level 1: Scans direct Followers or Following of the target account.\nLevel 2: Scans direct Followers/Following PLUS deep-scans followers of all qualified profiles found!")
                with cfg_l4:
                    match_logic = st.selectbox("Matching Logic Mode", ["Match ANY Keyword (Flex Mode)", "Match ALL Keywords (Strict Mode)"], index=0, key="cfg_match_logic", disabled=inputs_disabled, help="Match ANY Keyword: Qualified if any 1 target keyword is in bio.\nMatch ALL Keywords: Qualified only if all target keywords are in bio.")

            with tab_cfg_filters:
                cfg_f1, cfg_f2, cfg_f3 = st.columns(3)
                with cfg_f1:
                    min_followers = st.number_input("Min Followers", min_value=0, value=0, step=100, key="cfg_min_followers", disabled=inputs_disabled)
                with cfg_f2:
                    max_followers = st.number_input("Max Followers (0=Unlimited)", min_value=0, value=0, step=1000, key="cfg_max_followers", disabled=inputs_disabled)
                with cfg_f3:
                    st.markdown("<div class='desktop-spacer'></div>", unsafe_allow_html=True)
                    include_private = st.checkbox("Include Private Profiles", value=True, key="cfg_inc_private", disabled=inputs_disabled)

            with tab_cfg_neg:
                st.text_input(
                    "Exclude Keywords (Blacklist, comma-separated)",
                    value=", ".join(st.session_state.neg_kw_list) if st.session_state.neg_kw_list else "",
                    placeholder="Type blacklist words separated by commas (e.g. crypto, agency)...",
                    key="neg_kw_input_field",
                    disabled=inputs_disabled,
                    help="Type blacklist words directly in this box separated by commas. Accounts with any of these words will be disqualified!"
                )

        # SECONDARY CONTROLS TOOLBAR
        ctrl_col1, ctrl_col2, ctrl_col3, ctrl_col4 = st.columns([1, 1, 1, 1])
        with ctrl_col1:
            if st.session_state.is_running:
                if not st.session_state.is_paused:
                    if st.button("Pause Search", use_container_width=True):
                        st.session_state.is_paused = True
                        if st.session_state.engine:
                            st.session_state.engine.is_paused = True
                        st.rerun()
                else:
                    st.button("Paused", use_container_width=True, disabled=True)
            else:
                st.button("Pause Search", use_container_width=True, disabled=True)

        with ctrl_col2:
            if st.button("Stop Search", use_container_width=True, disabled=not st.session_state.is_running):
                if st.session_state.engine:
                    st.session_state.engine.is_running = False
                    st.session_state.engine.is_paused = False
                st.session_state.is_running = False
                st.session_state.is_paused = False
                st.rerun()

        with ctrl_col3:
            if st.button("Clear All Data", use_container_width=True, disabled=st.session_state.is_running):
                confirm_clear_all_dialog()

        with ctrl_col4:
            if st.button("Refresh Data", use_container_width=True):
                st.rerun()

        st.markdown("---")

    # ---------------------------------------------------------
    # 4. UNIFIED STAT BAR & METRICS DASHBOARD
    # ---------------------------------------------------------
    history_list = get_search_history()

    active_search_id = None
    sel_sid = st.session_state.get("selected_search_id", None)
    if st.session_state.engine and getattr(st.session_state.engine, "current_search_id", 0) > 0:
        active_search_id = st.session_state.engine.current_search_id
    elif sel_sid is not None:
        active_search_id = sel_sid
    elif history_list:
        active_search_id = history_list[0]["id"]

    if history_list:
        h_col1, h_col2 = st.columns([3.5, 1.5])
        with h_col1:
            session_options = {}
            for h in history_list:
                hid = h["id"]
                lbl = f"Search #{hid}: @{h.get('target_username')} ({h.get('keywords')}) - [{h.get('status')}]"
                session_options[lbl] = hid
            session_options["All Searches Combined"] = "ALL"

            selected_label = st.selectbox(
                "Select Search Session View",
                list(session_options.keys()),
                index=0,
                key="search_session_selector"
            )
            chosen_val = session_options[selected_label]
            if chosen_val == "ALL":
                active_search_id = None
            elif chosen_val is not None:
                active_search_id = chosen_val

    counts = get_counts(search_id=active_search_id)

    st.markdown(f"""
    <div class="stat-bar">
        <div class="stat-item">
            <div class="stat-num">{counts['total']:,}</div>
            <div class="stat-title">Total Evaluated</div>
        </div>
        <div class="stat-item">
            <div class="stat-num" style="color: #6EE7B7;">{counts['qualified']:,}</div>
            <div class="stat-title">Qualified Leads</div>
        </div>
        <div class="stat-item">
            <div class="stat-num" style="color: #FDE68A;">{counts['doubtful']:,}</div>
            <div class="stat-title">Needs Review</div>
        </div>
        <div class="stat-item">
            <div class="stat-num" style="color: #9CA3AF;">{counts['unqualified']:,}</div>
            <div class="stat-title">Unqualified</div>
        </div>
        <div class="stat-item">
            <div class="stat-num" style="color: #FCA5A5;">{counts['contacts']:,}</div>
            <div class="stat-title">Extracted Contacts</div>
        </div>
        <div class="stat-item">
            <div class="stat-num" style="color: #94A3B8;">{counts['private']:,}</div>
            <div class="stat-title">Private Profiles</div>
        </div>
    </div>
    """, unsafe_allow_html=True)

    st.markdown("---")

    # ---------------------------------------------------------
    # 5. FILTERS & EXPORT TOOLBAR
    # ---------------------------------------------------------
    st.markdown("##### Filter & Export Leads")
    f_col1, f_col2, f_col3, f_col4, f_col5, f_col6, f_col7 = st.columns([1.8, 0.9, 0.9, 0.9, 0.8, 0.8, 0.8])

    with f_col1:
        search_query = st.text_input("Search Filter", placeholder="Search username, bio, email, phone, or keyword...", label_visibility="collapsed")
    with f_col2:
        min_match_score = st.number_input("Min Match %", min_value=0, max_value=100, value=0, step=5, label_visibility="collapsed")
    with f_col3:
        max_followers_filter = st.number_input("Max Followers (0=All)", min_value=0, value=0, step=500, label_visibility="collapsed")
    with f_col4:
        category_filter_sel = st.selectbox("Category Filter", ["All Categories", "Qualified", "Needs Review", "Unqualified"], index=0, label_visibility="collapsed")
    with f_col5:
        privacy_filter_sel = st.selectbox("Profile Type", ["All Profiles", "Public Only", "Private Only"], index=0, label_visibility="collapsed")
    with f_col6:
        has_contact_check = st.checkbox("With Contact Only", value=False)

    cat_db_param = None
    if category_filter_sel == "Qualified":
        cat_db_param = "QUALIFIED"
    elif category_filter_sel == "Needs Review":
        cat_db_param = "DOUBTFUL"
    elif category_filter_sel == "Unqualified":
        cat_db_param = "UNQUALIFIED"

    priv_db_param = "ALL"
    if privacy_filter_sel == "Public Only":
        priv_db_param = "PUBLIC"
    elif privacy_filter_sel == "Private Only":
        priv_db_param = "PRIVATE"

    filtered_accounts = get_filtered_accounts(
        category_filter=cat_db_param,
        min_score=float(min_match_score),
        search_query=search_query,
        has_contact_only=has_contact_check,
        max_followers=int(max_followers_filter),
        privacy_filter=priv_db_param,
        search_id=active_search_id
    )

    # Export Data Generators
    df_export = pd.DataFrame(filtered_accounts)
    if not df_export.empty:
        export_cols = [c for c in ["username", "full_name", "category", "match_score", "email", "phone", "matched_keywords", "follower_count", "following_count", "bio", "is_private", "reason"] if c in df_export.columns]
        df_export = df_export[export_cols]

    with f_col7:
        if not df_export.empty:
            csv_bytes = df_export.to_csv(index=False).encode('utf-8')
            st.download_button("Export CSV", data=csv_bytes, file_name="instagram_leads.csv", mime="text/csv", use_container_width=True)
        else:
            st.button("Export CSV", disabled=True, use_container_width=True)

    st.markdown("---")

    # ---------------------------------------------------------
    # 6. MODAL DIALOGS (ACCOUNT DETAILS, DATA RESET & DELETION)
    # ---------------------------------------------------------
    @st.dialog("Confirm Data Reset")
    def confirm_clear_all_dialog():
        st.markdown("### Warning: Permanently Reset All Data?")
        st.write("Are you sure you want to delete all evaluated accounts, queues, and search history?")
        c1, c2 = st.columns(2)
        with c1:
            if st.button("Yes, Clear Everything", type="primary", use_container_width=True):
                clear_database()
                st.session_state.selected_usernames.clear()
                st.rerun()
        with c2:
            if st.button("Cancel", use_container_width=True):
                st.rerun()

    @st.dialog("Account Details")
    def show_account_details_dialog(acc):
        st.markdown(f"### @{acc['username']}")

        cat = acc['category']
        if cat == "QUALIFIED":
            badge_html = "<span class='badge badge-qualified'>QUALIFIED</span>"
        elif cat == "DOUBTFUL":
            badge_html = "<span class='badge badge-review'>NEEDS REVIEW</span>"
        else:
            badge_html = "<span class='badge badge-unqualified'>UNQUALIFIED</span>"

        score_val = acc.get('match_score', 0)
        st.markdown(f"**Full Name:** {acc['full_name'] or 'N/A'} &nbsp; | &nbsp; **Status:** {badge_html} &nbsp; | &nbsp; **Match Score:** `{score_val:.0f}%`", unsafe_allow_html=True)
        st.markdown(f"**Followers:** `{acc['follower_count']:,}` &nbsp; | &nbsp; **Following:** `{acc['following_count']:,}` &nbsp; | &nbsp; **Type:** `{'Private Profile' if acc['is_private'] else 'Public Profile'}`")

        if acc.get("bio"):
            st.markdown(f"**Bio:** {acc['bio']}")

        if acc.get("matched_keywords"):
            st.markdown(f"**Matched Keywords:** `{acc['matched_keywords']}`")

        if acc.get("reason"):
            st.markdown(f"**Reason:** {acc['reason']}")

        # Contact Info Section (Available vs Unextracted)
        email_val = acc.get('email')
        phone_val = acc.get('phone')

        st.markdown("<div style='border-bottom: 1px solid var(--border-subtle); margin: 12px 0;'></div>", unsafe_allow_html=True)

        if email_val or phone_val:
            st.markdown("**Extracted Contact Info:**")
            if email_val:
                st.success(f"Email: {email_val}")
            if phone_val:
                st.success(f"Phone: {phone_val}")
        else:
            st.caption("Contact Info (Email / Phone): Not Extracted for this profile")

        st.markdown("---")
        c_d1, c_d2, c_d3 = st.columns(3)
        with c_d1:
            st.link_button("Open Instagram", f"https://www.instagram.com/{acc['username']}/", use_container_width=True)
        with c_d2:
            if st.button("Mark Qualified", use_container_width=True):
                update_account_category(acc['username'], "QUALIFIED")
                st.rerun()
        with c_d3:
            if st.button("Delete Account", use_container_width=True, type="primary"):
                delete_account(acc['username'])
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
    # 7. ZERO-GAP GOOGLE SHEETS SPREADSHEET GRID RESULTS UI
    # ---------------------------------------------------------
    tab_all, tab_qual, tab_review, tab_unqual, tab_logs = st.tabs([
        "All Results",
        "Qualified",
        "Needs Review",
        "Unqualified",
        "System Activity"
    ])

    def render_account_list(accounts_list, tab_key="all"):
        if not accounts_list:
            st.markdown("""
            <div style="background: rgba(13, 14, 18, 0.8); border: 1px dashed var(--border-subtle); border-radius: 8px; padding: 24px; text-align: center; margin: 1.5rem 0;">
                <div style="font-size: 0.95rem; font-weight: 700; color: #F8FAFC; text-transform: uppercase; letter-spacing: 0.05em;">No Accounts Evaluated for this Search Session</div>
                <div style="font-size: 0.82rem; color: #94A3B8; margin-top: 6px;">
                    Enter a <b>Target Username</b> and <b>Keywords</b> above, then click <b>Start Search</b> to begin scanning!
                </div>
            </div>
            """, unsafe_allow_html=True)
            return

        b_col1, b_col2 = st.columns([3, 1])
        with b_col2:
            num_sel = len(st.session_state.selected_usernames)
            if st.button(f"Delete Selected ({num_sel})", disabled=num_sel == 0, key=f"btn_del_sel_{tab_key}", use_container_width=True):
                confirm_batch_delete_dialog(list(st.session_state.selected_usernames))

        # Google Sheets Spreadsheet Grid Table Header
        t_h1, t_h2, t_h3, t_h4, t_h5 = st.columns([0.4, 3.4, 1.4, 0.8, 1.6])
        with t_h1:
            st.markdown("<div class='sheet-grid-header'>SELECT</div>", unsafe_allow_html=True)
        with t_h2:
            st.markdown("<div class='sheet-grid-header'>ACCOUNT USERNAME & NAME</div>", unsafe_allow_html=True)
        with t_h3:
            st.markdown("<div class='sheet-grid-header'>CATEGORY STATUS</div>", unsafe_allow_html=True)
        with t_h4:
            st.markdown("<div class='sheet-grid-header'>MATCH</div>", unsafe_allow_html=True)
        with t_h5:
            st.markdown("<div class='sheet-grid-header'>ACTIONS</div>", unsafe_allow_html=True)

        # Google Sheets Grid Rows (Zero Vertical Gap Seamless Sheet Layout)
        for acc in accounts_list:
            cat = acc["category"]
            if cat == "QUALIFIED":
                badge_html = '<span class="badge badge-qualified">QUALIFIED</span>'
            elif cat == "DOUBTFUL":
                badge_html = '<span class="badge badge-review">NEEDS REVIEW</span>'
            else:
                badge_html = '<span class="badge badge-unqualified">UNQUALIFIED</span>'

            score_val = acc.get("match_score", 0.0)

            c_check, c_user, c_stat, c_score, c_actions = st.columns([0.4, 3.4, 1.4, 0.8, 1.6])

            with c_check:
                is_selected = acc['username'] in st.session_state.selected_usernames
                chk = st.checkbox(f"Select @{acc['username']}", value=is_selected, key=f"chk_{tab_key}_{acc['username']}", label_visibility="collapsed")
                if chk:
                    st.session_state.selected_usernames.add(acc['username'])
                else:
                    st.session_state.selected_usernames.discard(acc['username'])

            with c_user:
                full_name_str = f" <span style='color:#64748B; font-size:0.8rem;'>({acc['full_name']})</span>" if acc['full_name'] else ""
                st.markdown(f"<div class='sheet-grid-cell'><b>@{acc['username']}</b>{full_name_str}</div>", unsafe_allow_html=True)

            with c_stat:
                st.markdown(f"<div class='sheet-grid-cell'>{badge_html}</div>", unsafe_allow_html=True)

            with c_score:
                st.markdown(f"<div class='sheet-grid-cell'><span style='font-family:\"JetBrains Mono\", monospace; font-weight:700; color:#F8FAFC;'>{score_val:.0f}%</span></div>", unsafe_allow_html=True)

            with c_actions:
                ac1, ac2 = st.columns([1, 1])
                with ac1:
                    if st.button("Details", key=f"det_{tab_key}_{acc['username']}", use_container_width=True):
                        show_account_details_dialog(acc)
                with ac2:
                    if st.button("Delete", key=f"del_{tab_key}_{acc['username']}", use_container_width=True):
                        delete_account(acc['username'])
                        st.session_state.selected_usernames.discard(acc['username'])
                        st.rerun()

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
        st.markdown("##### System Activity Status")
        if st.session_state.engine and st.session_state.engine.logs:
            st.success("Agent process is active. Processing candidate profiles in real-time.")
            with st.expander("Developer Debug Logs", expanded=False):
                st.code("\n".join(st.session_state.engine.logs[-200:]), language="text")
        else:
            st.info("System is idle. Start a search session to begin scanning.")

    # Sync state
    if st.session_state.engine and thread_alive:
        st.session_state.is_running = st.session_state.engine.is_running
        st.session_state.is_paused = st.session_state.engine.is_paused
    else:
        st.session_state.is_running = False


def render_reel_automation_tab():

    st.markdown('''
    <div style="background: var(--bg-surface); border: 1px solid var(--border-subtle); border-radius: 8px; padding: 18px; margin-bottom: 1.2rem;">
        <div style="color: #F8FAFC; font-size: 1.05rem; font-weight: 700; text-transform: uppercase; letter-spacing: 0.05em;">
            Reel Share Automation Engine
        </div>
        <div style="color: #94A3B8; font-size: 0.82rem; margin-top: 4px;">
            Automatically send Instagram Reels to selected friends with human-like randomized delays during your scheduled time window (e.g. 09:00 PM to 11:00 PM).
        </div>
    </div>
    ''', unsafe_allow_html=True)

    r_col1, r_col2 = st.columns([1, 1])

    with r_col1:
        st.markdown("##### Session Credentials & Recipient Settings")
        saved_sid = st.session_state.get("saved_sessionid", "")
        
        reel_sid_in = st.text_input("Instagram Session ID Cookie", value=saved_sid, type="password", placeholder="Paste Instagram sessionid cookie...", key="reel_sid_input", help="Authenticated Session ID cookie from Instagram.")
        
        if st.button("Verify Session ID", use_container_width=True, key="btn_verify_sid_tab2"):
            st.session_state["main_nav_tab"] = TAB_REELS
            if reel_sid_in.strip():
                with st.spinner("Verifying Session ID with Instagram..."):
                    is_valid, v_user, msg = st.session_state.reel_engine.verify_sessionid(reel_sid_in.strip())
                    if is_valid:
                        st.session_state.sid_verified_status = (True, v_user, msg)
                    else:
                        st.session_state.sid_verified_status = (False, "", msg)
            else:
                st.error("Please enter a Session ID first.")

        if "sid_verified_status" in st.session_state and st.session_state.sid_verified_status:
            v_ok, v_user, v_msg = st.session_state.sid_verified_status
            if v_ok:
                st.markdown(f"""
                <div style="background: rgba(16, 185, 129, 0.12); border: 1px solid rgba(16, 185, 129, 0.35); border-radius: 6px; padding: 8px 12px; margin-top: 6px; margin-bottom: 10px; width: 100%; box-sizing: border-box; word-break: break-word; overflow-wrap: anywhere;">
                    <span style="color: #10B981; font-weight: 700; font-size: 0.8rem; text-transform: uppercase; letter-spacing: 0.04em;">AUTHENTICATED INSTAGRAM USER:</span>
                    <span style="color: #F8FAFC; font-weight: 700; font-size: 0.88rem; margin-left: 4px;">@{v_user or 'Verified User'}</span>
                    <div style="color: #6EE7B7; font-size: 0.76rem; margin-top: 2px;">{v_msg}</div>
                </div>
                """, unsafe_allow_html=True)
            else:
                st.error(f"Session Error: {v_msg}")

        reel_target_in = st.text_input(
            "Target Recipient Username(s)",
            value="",
            placeholder="e.g. @username1, @username2",
            key="reel_target_input",
            help="Format: Every recipient handle must start with @ (e.g. @username1, @username2). Separate multiple usernames with commas."
        )

        valid_recipients = []
        recipient_has_error = False

        if reel_target_in.strip():
            raw_recips = [t.strip() for t in reel_target_in.split(",") if t.strip()]
            invalid_no_at = []
            invalid_chars = []
            import re

            for item in raw_recips:
                if not item.startswith("@"):
                    invalid_no_at.append(item)
                else:
                    handle = item[1:]
                    if re.match(r'^[a-zA-Z0-9._]{1,30}$', handle):
                        valid_recipients.append(handle)
                    else:
                        invalid_chars.append(item)

            if invalid_no_at:
                recipient_has_error = True
                st.error(f"⚠️ Recipient handles must start with '@' (e.g. @{invalid_no_at[0]}). Please add '@' before the username.")
            elif invalid_chars:
                recipient_has_error = True
                st.error(f"⚠️ Invalid Instagram username format: '{invalid_chars[0]}'. Handles can only contain letters, numbers, dots, and underscores.")
            elif valid_recipients:
                recips_display = ", @".join(valid_recipients)
                st.markdown(f"""
                <div style="background: rgba(16, 185, 129, 0.12); border: 1px solid rgba(16, 185, 129, 0.35); border-radius: 6px; padding: 8px 12px; margin-top: 4px; margin-bottom: 10px; width: 100%; box-sizing: border-box; word-break: break-word; overflow-wrap: anywhere;">
                    <span style="color: #10B981; font-weight: 700; font-size: 0.78rem; text-transform: uppercase; letter-spacing: 0.04em;">Confirmed Recipient(s):</span>
                    <span style="color: #F8FAFC; font-weight: 600; font-size: 0.88rem; margin-left: 4px;">@{recips_display}</span>
                </div>
                """, unsafe_allow_html=True)

        reel_source_mode = st.radio(
            "Reel Source Mode",
            ["Custom Reel Links", "Auto-Discover Random Reels from Feed"],
            horizontal=True,
            key="reel_source_mode_radio"
        )

        if reel_source_mode == "Auto-Discover Random Reels from Feed":
            total_reels_count = st.number_input("Total Reels to Send", min_value=1, max_value=500, value=15, step=1, key="reel_count_input")
        else:
            total_reels_count = 15

    with r_col2:
        st.markdown("##### 12-Hour Schedule Window")
        
        t_start_col, t_to_col, t_end_col = st.columns([2.5, 0.5, 2.5])
        with t_start_col:
            st_h, st_m, st_ap = st.columns([1, 1, 1.2])
            with st_h:
                sh_val = st.text_input("Hour", value="09", placeholder="09", key="start_hour_in")
            with st_m:
                sm_val = st.text_input("Min", value="00", placeholder="00", key="start_min_in")
            with st_ap:
                sap_val = st.selectbox("Format", ["PM", "AM"], index=0, key="start_ampm_in")
            start_time_val = f"{sh_val.strip()}:{sm_val.strip()} {sap_val.strip()}"

        with t_to_col:
            st.markdown("<div style='text-align: center; margin-top: 32px; font-weight: 700; color: #94A3B8; font-size: 0.95rem;'>to</div>", unsafe_allow_html=True)

        with t_end_col:
            et_h, et_m, et_ap = st.columns([1, 1, 1.2])
            with et_h:
                eh_val = st.text_input("Hour", value="11", placeholder="11", key="end_hour_in")
            with et_m:
                em_val = st.text_input("Min", value="00", placeholder="00", key="end_min_in")
            with et_ap:
                eap_val = st.selectbox("Format", ["PM", "AM"], index=0, key="end_ampm_in")
            end_time_val = f"{eh_val.strip()}:{em_val.strip()} {eap_val.strip()}"

        st.markdown("<div style='margin-top:10px;'></div>", unsafe_allow_html=True)

        if reel_source_mode == "Custom Reel Links":
            reel_urls_in = st.text_area("Reel URLs (one per line)", value="", placeholder="Paste Instagram Reel links to share, one link per line...", height=110, key="reel_urls_input")
            urls_parsed = [u.strip() for u in reel_urls_in.split("\n") if u.strip()]
            total_reels_count = len(urls_parsed) if urls_parsed else 1
            auto_discover_cb = False
        else:
            st.info("Auto-Discover Active: Playwright browser will automatically scroll your Instagram feed, discover fresh Reels, and send them to your recipient.")
            reel_urls_in = ""
            auto_discover_cb = True

    st.markdown("---")
    c_btn1, c_btn2, c_btn3, c_btn4, c_btn5 = st.columns([1.4, 1.4, 1, 1, 1])

    reel_eng: ReelAutomationEngine = st.session_state.reel_engine
    daemon = get_daemon_instance()

    with c_btn1:
        if not reel_eng.is_running:
            if st.button("Instant Start Now", type="primary", use_container_width=True, key="btn_start_reel_auto"):
                if not reel_sid_in.strip():
                    st.error("Please enter a valid Instagram Session ID!")
                elif recipient_has_error or not valid_recipients:
                    st.error("Please enter valid recipient handle(s) starting with '@' (e.g. @username1)!")
                elif not reel_urls_in.strip() and not auto_discover_cb:
                    st.error("Please enter at least 1 Reel URL OR select Auto-Discover mode!")
                else:
                    with st.spinner("Confirming Session ID with Instagram..."):
                        is_valid, v_user, msg = reel_eng.verify_sessionid(reel_sid_in.strip())

                    if not is_valid:
                        st.error(f"Session ID Verification Failed: {msg}. Please check your sessionid!")
                    else:
                        st.session_state.sid_verified_status = (True, v_user, msg)
                        st.session_state["main_nav_tab"] = TAB_REELS
                        targets = valid_recipients
                        urls = [u.strip() for u in reel_urls_in.split("\n") if u.strip()]
                        reel_eng.sessionid = reel_sid_in.strip()
                        reel_eng.start_automation(
                            recipients=targets,
                            reel_urls=urls,
                            total_reels=int(total_reels_count),
                            start_time_str=start_time_val.strip(),
                            end_time_str=end_time_val.strip(),
                            auto_discover=auto_discover_cb
                        )
                        st.success(f"Verified Session ID for @{v_user or 'User'}! Reel Automation Started for @{', @'.join(targets)}")
                        st.rerun()

        else:
            st.button("Automation Running...", disabled=True, use_container_width=True, key="btn_running_reel_auto")

    with c_btn2:
        if st.button("Save Offline Schedule", use_container_width=True, key="btn_save_bg_schedule"):
            if not reel_sid_in.strip():
                st.error("Please enter a valid Instagram Session ID!")
            elif recipient_has_error or not valid_recipients:
                st.error("Please enter valid recipient handle(s) starting with '@' (e.g. @username1)!")
            elif not reel_urls_in.strip() and not auto_discover_cb:
                st.error("Please enter at least 1 Reel URL OR select Auto-Discover mode!")
            else:
                with st.spinner("Confirming Session ID with Instagram..."):
                    is_valid, v_user, msg = reel_eng.verify_sessionid(reel_sid_in.strip())

                if not is_valid:
                    st.error(f"Session ID Verification Failed: {msg}. Please check your sessionid!")
                else:
                    st.session_state.sid_verified_status = (True, v_user, msg)
                    st.session_state["main_nav_tab"] = TAB_REELS
                    task_id = add_scheduled_task(
                        sessionid=reel_sid_in.strip(),
                        recipients=",".join([f"@{r}" for r in valid_recipients]),
                        reel_urls=reel_urls_in.strip() if reel_urls_in.strip() else "AUTO_DISCOVER",
                        total_reels=int(total_reels_count),
                        start_time=start_time_val.strip(),
                        end_time=end_time_val.strip()
                    )
                    daemon.start_daemon()
                    st.success(f"Verified Session ID for @{v_user or 'User'}! Task #{task_id} saved to Background Daemon.")
                    st.rerun()


    with c_btn3:
        if reel_eng.is_running:
            if reel_eng.is_paused:
                if st.button("Resume", use_container_width=True, key="btn_resume_reel_auto"):
                    reel_eng.resume_automation()
                    st.rerun()
            else:
                if st.button("Pause", use_container_width=True, key="btn_pause_reel_auto"):
                    reel_eng.pause_automation()
                    st.rerun()
        else:
            st.button("Pause", disabled=True, use_container_width=True, key="btn_pause_reel_auto_dis")

    with c_btn4:
        if st.button("Stop", use_container_width=True, disabled=not reel_eng.is_running, key="btn_stop_reel_auto"):
            reel_eng.stop_automation()
            st.rerun()

    with c_btn5:
        if st.button("Clear Logs", use_container_width=True, key="btn_clear_reel_logs"):
            clear_reel_logs()
            reel_eng.logs = []
            st.rerun()

    st.markdown("<br>", unsafe_allow_html=True)
    m_col1, m_col2, m_col3, m_col4 = st.columns(4)
    with m_col1:
        daemon_status = "DAEMON ACTIVE (BACKGROUND)" if daemon.is_running else "DAEMON STOPPED"
        st.metric("Daemon Status", daemon_status)
    with m_col2:
        st.metric("Reels Sent", f"{reel_eng.sent_count} / {reel_eng.total_reels}")
    with m_col3:
        st.metric("Failed", reel_eng.failed_count)
    with m_col4:
        if reel_eng.next_run_timestamp and reel_eng.is_running:
            rem = max(0, int(reel_eng.next_run_timestamp - time.time()))
            st.metric("Next Reel In", f"{rem}s")
        else:
            st.metric("Next Reel In", "--")

    log_tab1, log_tab2, log_tab3 = st.tabs(["📋 Activity Console Logs", "📜 Sent Reels Database Log", "📅 Background Offline Schedules"])
    with log_tab1:
        if reel_eng.logs:
            st.code("\n".join(reel_eng.logs[-100:]), language="text")
        else:
            st.info("No activity logs yet. Configure settings and click 'Instant Start Now' or 'Save Offline Schedule'.")

    with log_tab2:
        db_logs = get_reel_logs(limit=100)
        if db_logs:
            df_logs = pd.DataFrame(db_logs)
            st.dataframe(df_logs, use_container_width=True)
        else:
            st.info("No reel history logs found in SQLite database.")

    with log_tab3:
        st.markdown("##### Background Task Schedules (Runs Even When Browser Closed)")
        sched_tasks = get_all_scheduled_tasks()
        if sched_tasks:
            df_sched = pd.DataFrame(sched_tasks)
            st.dataframe(df_sched, use_container_width=True)
            
            s_del1, s_del2 = st.columns([2, 1])
            with s_del1:
                task_ids = [t["id"] for t in sched_tasks]
                sel_del_id = st.selectbox("Select Schedule Task ID to Cancel/Delete", task_ids)
            with s_del2:
                st.markdown("<div style='margin-top:28px;'></div>", unsafe_allow_html=True)
                if st.button("Delete Task Schedule", type="primary", use_container_width=True):
                    if sel_del_id:
                        delete_scheduled_task(int(sel_del_id))
                        st.success(f"Deleted Task #{sel_del_id}")
                        st.rerun()
        else:
            st.info("No offline background schedules found. Fill the form above and click 'Save Offline Schedule'!")

# Main render execution with persistent navigation state
if "main_nav_tab" not in st.session_state:
    st.session_state.main_nav_tab = TAB_LEADS

selected_tab = st.segmented_control(
    "Main Navigation",
    options=[TAB_LEADS, TAB_REELS],
    default=st.session_state.main_nav_tab,
    key="main_nav_tab",
    label_visibility="collapsed"
)

current_view = selected_tab or st.session_state.get("main_nav_tab", TAB_LEADS)

if current_view == TAB_LEADS:
    render_account_finder_tab()
else:
    render_reel_automation_tab()

