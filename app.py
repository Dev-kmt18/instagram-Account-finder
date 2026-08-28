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
    get_pending_queue_count, get_search_history
)
from insta_bot.scraper import InstagramAgentEngine
from insta_bot.config import MIN_DELAY_PER_PROFILE, MAX_DELAY_PER_PROFILE

# Top-level Vercel Python entrypoint export compatibility
app = application = handler = None

# Page Configuration
st.set_page_config(
    page_title="Instagram Lead Finder & Classifier",
    page_icon="🎯",
    layout="wide",
    initial_sidebar_state="collapsed"
)

# Initialize Database (WAL mode & auto-migrations)
init_db()

# Custom Styling (Refined Graphite Dark Theme inspired by Linear/Vercel)
st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@500;600;700&display=swap');

    :root {
        --bg-base: #0E1015;
        --bg-surface: #151821;
        --bg-surface-elevated: #1B1E29;
        --bg-input: #12141C;
        --border-subtle: rgba(255, 255, 255, 0.08);
        --border-hover: rgba(91, 110, 245, 0.4);
        --text-primary: #F1F5F9;
        --text-secondary: #94A3B8;
        --text-muted: #64748B;
        --accent: #5B6EF5;
        --accent-hover: #4C5EE8;
        --accent-glow: rgba(91, 110, 245, 0.2);
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
        margin-bottom: 1.5rem;
        padding-bottom: 1rem;
        border-bottom: 1px solid var(--border-subtle);
        display: flex;
        align-items: center;
        justify-content: space-between;
    }
    .app-title {
        font-size: 1.6rem;
        font-weight: 700;
        color: #F8FAFC;
        letter-spacing: -0.025em;
        display: flex;
        align-items: center;
        gap: 10px;
    }
    .app-subtitle {
        font-size: 0.85rem;
        color: var(--text-secondary);
        margin-top: 0.25rem;
    }

    /* Section Card Containers */
    .hero-card {
        background: var(--bg-surface);
        border: 1px solid var(--border-subtle);
        border-radius: 12px;
        padding: 20px;
        margin-bottom: 1.25rem;
        box-shadow: 0 4px 20px rgba(0, 0, 0, 0.2);
    }

    .section-label {
        font-size: 0.75rem;
        font-weight: 700;
        text-transform: uppercase;
        letter-spacing: 0.06em;
        color: var(--accent);
        margin-bottom: 0.75rem;
        display: flex;
        align-items: center;
        gap: 6px;
    }

    /* Custom Input Controls Styling */
    .stTextInput input, .stNumberInput input, .stSelectbox select {
        background-color: var(--bg-input) !important;
        color: var(--text-primary) !important;
        border: 1px solid var(--border-subtle) !important;
        border-radius: 8px !important;
        font-size: 0.9rem !important;
        transition: border-color 0.15s ease, box-shadow 0.15s ease !important;
    }
    .stTextInput input:focus, .stNumberInput input:focus, .stSelectbox select:focus {
        border-color: var(--accent) !important;
        box-shadow: 0 0 0 2px var(--accent-glow) !important;
    }

    /* Status Badges */
    .badge {
        display: inline-flex;
        align-items: center;
        gap: 6px;
        padding: 3px 10px;
        border-radius: 20px;
        font-size: 0.78rem;
        font-weight: 600;
        letter-spacing: 0.01em;
    }
    .badge-qualified {
        background-color: rgba(16, 185, 129, 0.12);
        color: #34D399;
        border: 1px solid rgba(16, 185, 129, 0.3);
    }
    .badge-review {
        background-color: rgba(245, 158, 11, 0.12);
        color: #FBBF24;
        border: 1px solid rgba(245, 158, 11, 0.3);
    }
    .badge-unqualified {
        background-color: rgba(239, 68, 68, 0.12);
        color: #FCA5A5;
        border: 1px solid rgba(239, 68, 68, 0.3);
    }
    .badge-contact {
        background-color: rgba(91, 110, 245, 0.12);
        color: #818CF8;
        border: 1px solid rgba(91, 110, 245, 0.3);
        font-size: 0.75rem;
        padding: 2px 8px;
    }

    /* Agent Status Badges */
    .running-cyclist {
        background: rgba(91, 110, 245, 0.15);
        color: #818CF8;
        border: 1px solid rgba(91, 110, 245, 0.4);
        padding: 6px 14px;
        border-radius: 20px;
        font-size: 0.82rem;
        font-weight: 600;
        display: inline-flex;
        align-items: center;
        gap: 6px;
    }
    .paused-badge {
        background: rgba(245, 158, 11, 0.15);
        color: #FCD34D;
        border: 1px solid rgba(245, 158, 11, 0.4);
        padding: 6px 14px;
        border-radius: 20px;
        font-size: 0.82rem;
        font-weight: 600;
    }

    /* Unified Stat Bar */
    .stat-bar {
        background: var(--bg-surface);
        border: 1px solid var(--border-subtle);
        border-radius: 12px;
        padding: 16px 20px;
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
        font-size: 1.5rem;
        font-weight: 700;
        color: #F8FAFC;
        line-height: 1.2;
    }
    .stat-title {
        font-size: 0.72rem;
        font-weight: 600;
        text-transform: uppercase;
        letter-spacing: 0.05em;
        color: var(--text-secondary);
        margin-top: 4px;
    }

    /* Lead Card Container with Hover State */
    .lead-card {
        background: var(--bg-surface);
        border: 1px solid var(--border-subtle);
        border-radius: 10px;
        padding: 16px 18px;
        margin-bottom: 10px;
        transition: transform 0.15s ease, border-color 0.15s ease;
    }
    .lead-card:hover {
        border-color: var(--border-hover);
        transform: translateY(-1px);
    }

    /* Custom Button Overrides for Primary vs Ghost Actions */
    div.stButton > button[kind="primary"] {
        background-color: var(--accent) !important;
        color: #FFFFFF !important;
        border: none !important;
        font-weight: 600 !important;
        border-radius: 8px !important;
        box-shadow: 0 4px 12px var(--accent-glow) !important;
        transition: all 0.15s ease !important;
    }
    div.stButton > button[kind="primary"]:hover {
        background-color: var(--accent-hover) !important;
        box-shadow: 0 6px 16px rgba(91, 110, 245, 0.35) !important;
    }

    div.stButton > button[kind="secondary"] {
        background-color: var(--bg-surface-elevated) !important;
        color: var(--text-primary) !important;
        border: 1px solid var(--border-subtle) !important;
        border-radius: 8px !important;
        font-weight: 500 !important;
        transition: all 0.15s ease !important;
    }
    div.stButton > button[kind="secondary"]:hover {
        border-color: var(--border-hover) !important;
        color: #FFFFFF !important;
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

# Synchronize state with background engine actively
if st.session_state.engine:
    st.session_state.is_running = st.session_state.engine.is_running
    st.session_state.is_paused = st.session_state.engine.is_paused

# Reactivity Engine: Refresh automatically EVERY 2.5 seconds WITHOUT UI Freeze while crawling
if st.session_state.is_running and not st.session_state.is_paused:
    st_autorefresh(interval=2500, limit=None, key="crawl_auto_refresh")

inputs_disabled = st.session_state.is_running and not st.session_state.is_paused

# ---------------------------------------------------------
# 1. HEADER
# ---------------------------------------------------------
status_badge_html = ""
if st.session_state.is_running and not st.session_state.is_paused:
    status_badge_html = '<span class="running-cyclist">⚡ Agent Active & Scanning...</span>'
elif st.session_state.is_running and st.session_state.is_paused:
    status_badge_html = '<span class="paused-badge">⏸ Agent Paused</span>'

st.markdown(
    f'<div class="app-header">'
    f'<div>'
    f'<div class="app-title">🎯 Instagram Lead Finder & Classifier</div>'
    f'<div class="app-subtitle">Extract followers or following, evaluate bio metadata, parse contact emails/phones & classify sales prospects.</div>'
    f'</div>'
    f'<div>{status_badge_html}</div>'
    f'</div>',
    unsafe_allow_html=True
)

# ---------------------------------------------------------
# 2. STEP 1: AUTHENTICATION
# ---------------------------------------------------------
if not st.session_state.is_authenticated:
    st.markdown("""
    <div style="background: var(--bg-surface); border: 1px solid var(--border-subtle); border-radius: 12px; padding: 20px; margin-bottom: 1.25rem;">
        <div style="color: #F8FAFC; font-size: 1rem; font-weight: 700; display: flex; align-items: center; gap: 8px;">
            <span>🔐 Step 1: Connect Instagram Account</span>
        </div>
        <div style="color: #94A3B8; font-size: 0.82rem; margin-top: 4px; margin-bottom: 14px;">
            Enter your Session ID or Instagram credentials to unlock lead crawling parameters and quality filters.
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
                sessionid_input_val = st.text_input("Session ID", type="password", placeholder="Paste your Instagram sessionid cookie value here...", label_visibility="collapsed")
            with c_sid_btn:
                if st.button("🔐 Connect Account", type="primary", use_container_width=True):
                    if sessionid_input_val and len(sessionid_input_val.strip()) > 5:
                        with st.spinner("Verifying session cookie with Instagram..."):
                            eng = InstagramAgentEngine(sessionid=sessionid_input_val)
                            if eng.login():
                                st.session_state.engine = eng
                                st.session_state.saved_sessionid = sessionid_input_val.strip()
                                st.session_state.is_authenticated = True
                                st.session_state.auth_user = eng.username or "Session Cookie"
                                st.success("🎉 Connected successfully!")
                                st.rerun()
                            else:
                                last_err = eng.logs[-1] if eng.logs else "Invalid session cookie"
                                st.error(f"Authentication Failed: {last_err}")
                    else:
                        st.error("Please enter a valid sessionid cookie.")
        else:
            if not st.session_state.awaiting_otp:
                c_u1, c_u2, c_u3 = st.columns([1.5, 1.5, 1])
                with c_u1:
                    u_val = st.text_input("Username", placeholder="Instagram username...", label_visibility="collapsed")
                with c_u2:
                    p_val = st.text_input("Password", type="password", placeholder="Instagram password...", label_visibility="collapsed")
                with c_u3:
                    if st.button("🔐 Login Account", type="primary", use_container_width=True):
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
                                    st.success(f"🎉 Connected as @{st.session_state.auth_user}!")
                                    st.rerun()
                                else:
                                    last_err = eng.logs[-1] if eng.logs else "Login failed"
                                    st.error(f"Authentication Failed: {last_err}")
                        else:
                            st.error("Please enter both username and password.")
            else:
                st.markdown("""
                <div style="background: rgba(91, 110, 245, 0.12); border: 1px solid #5B6EF5; border-radius: 8px; padding: 10px 14px; margin-bottom: 0.8rem;">
                    <span style="color: #818CF8; font-weight: 600; font-size: 0.92rem;">🔐 Two-Factor Authentication (OTP) Required</span>
                    <div style="color: #CBD5E1; font-size: 0.8rem; margin-top: 2px;">Enter the 6-digit verification code sent to your phone/app.</div>
                </div>
                """, unsafe_allow_html=True)
                otp_c1, otp_c2, otp_c3 = st.columns([2, 1, 1])
                with otp_c1:
                    otp_val_in = st.text_input("6-Digit OTP", placeholder="Enter 6-digit code...", label_visibility="collapsed", key="otp_in_step1")
                with otp_c2:
                    if st.button("✅ Confirm OTP", type="primary", use_container_width=True):
                        if otp_val_in and st.session_state.engine:
                            if st.session_state.engine.confirm_two_factor(otp_val_in):
                                st.session_state.awaiting_otp = False
                                st.session_state.is_authenticated = True
                                st.session_state.auth_user = st.session_state.engine.username
                                st.success("🎉 OTP Verified & Connected!")
                                st.rerun()
                            else:
                                st.error("❌ Invalid OTP code.")
                        else:
                            st.error("Please enter the 6-digit OTP code.")
                with otp_c3:
                    if st.button("❌ Cancel", use_container_width=True):
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
        <div style="background: rgba(16, 185, 129, 0.08); border: 1px solid rgba(16, 185, 129, 0.25); border-radius: 8px; padding: 8px 14px; display: flex; align-items: center; gap: 8px; margin-bottom: 0.8rem;">
            <span style="color: #10B981; font-weight: 700; font-size: 0.88rem;">🟢 Connected Account:</span>
            <span style="color: #F8FAFC; font-weight: 600; font-size: 0.88rem;">@{st.session_state.auth_user}</span>
            <span style="color: #94A3B8; font-size: 0.78rem;">— Active & Ready for Lead Scraping</span>
        </div>
        """, unsafe_allow_html=True)
    with b_col2:
        if st.button("🔄 Disconnect", use_container_width=True, disabled=inputs_disabled):
            st.session_state.is_authenticated = False
            st.session_state.engine = None
            st.session_state.auth_user = ""
            st.rerun()

    # PRIMARY ACTION ZONE HERO CARD
    st.markdown("""
    <div style="background: var(--bg-surface); border: 1px solid var(--border-subtle); border-radius: 12px; padding: 18px 20px; margin-bottom: 1rem;">
        <div style="font-size: 0.75rem; font-weight: 700; text-transform: uppercase; letter-spacing: 0.06em; color: var(--accent); margin-bottom: 10px;">
            🎯 Primary Action Zone
        </div>
    </div>
    """, unsafe_allow_html=True)

    hero_c1, hero_c2, hero_c3 = st.columns([2.5, 1.5, 1.5])
    
    with hero_c1:
        target_username = st.text_input("Target Account Username", placeholder="e.g. pawan_kmt18", disabled=inputs_disabled)
    with hero_c2:
        search_mode = st.selectbox("Search Mode", ["followers", "following", "both"], index=0, disabled=inputs_disabled)
    with hero_c3:
        st.markdown("<div style='margin-top: 28px;'></div>", unsafe_allow_html=True)
        pending_queue_count = get_pending_queue_count()
        if not st.session_state.is_running:
            if st.button("▶️ Start Search", use_container_width=True, type="primary"):
                final_kws = list(st.session_state.kw_list)
                typed_kw = st.session_state.get("kw_input_field", "").strip()
                if typed_kw:
                    for k in typed_kw.split(","):
                        clean_k = k.strip().lower()
                        if clean_k and clean_k not in final_kws:
                            final_kws.append(clean_k)

                if not target_username and pending_queue_count == 0:
                    st.error("Please enter Target Username!")
                elif not final_kws:
                    st.error("Please add at least 1 keyword!")
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
                                eng.log(f"❌ Crawl Error: {thread_err}")
                                eng.is_running = False

                    t = threading.Thread(
                        target=run_thread,
                        args=(
                            engine_ref, target_username, final_kws, st.session_state.neg_kw_list,
                            1000, search_mode, 1, "total", "OR",
                            0, 0, True
                        ),
                        daemon=True
                    )
                    st.session_state.crawl_thread = t
                    t.start()
                    st.rerun()
        else:
            if st.session_state.is_paused:
                if st.button("▶️ Resume Search", use_container_width=True, type="primary"):
                    st.session_state.is_paused = False
                    if st.session_state.engine:
                        st.session_state.engine.is_paused = False
                    st.rerun()
            else:
                st.button("▶️ Scanning Active...", use_container_width=True, disabled=True)

    # ADVANCED CONFIGURATION AREA (COLLAPSIBLE TABS)
    with st.expander("⚙️ Advanced Settings & Keyword Filters", expanded=True):
        tab_cfg_kws, tab_cfg_limits, tab_cfg_filters, tab_cfg_neg = st.tabs([
            "🎯 Target Keywords",
            "📊 Limits & Depth",
            "🛡️ Quality Filters",
            "🚫 Blacklist / Exclude"
        ])

        with tab_cfg_kws:
            def on_add_kw():
                val = st.session_state.get("kw_input_field", "").strip()
                if val:
                    if "," in val:
                        parts = [k.strip().lower() for k in val.split(",") if k.strip()]
                    else:
                        parts = [val.lower()]
                    for p in parts:
                        if p not in st.session_state.kw_list:
                            st.session_state.kw_list.append(p)
                        if p not in st.session_state.recent_keywords:
                            st.session_state.recent_keywords.append(p)
                    st.session_state["kw_input_field"] = ""

            st.text_input("Add Target Keyword", placeholder="Type keyword and press Enter (e.g. mbbs, kolkata)...", key="kw_input_field", on_change=on_add_kw, disabled=inputs_disabled)
            
            if st.session_state.kw_list:
                st.markdown("<div style='font-size:0.75rem; color:var(--accent); font-weight:600; margin-top:6px; margin-bottom:4px;'>Active Target Keywords:</div>", unsafe_allow_html=True)
                chip_cols = st.columns(min(len(st.session_state.kw_list), 6))
                for idx, kw in enumerate(list(st.session_state.kw_list)):
                    c_idx = idx % min(len(st.session_state.kw_list), 6)
                    if chip_cols[c_idx].button(f"🏷️ {kw} ✖", key=f"del_pos_kw_{idx}_{kw}", disabled=inputs_disabled, help=f"Click to remove '{kw}'"):
                        st.session_state.kw_list.remove(kw)
                        st.rerun()
                
                if st.button("Clear All Keywords", key="clr_pos_kws", disabled=inputs_disabled):
                    st.session_state.kw_list = []
                    st.rerun()

            recent_to_show = [rk for rk in st.session_state.recent_keywords if rk not in st.session_state.kw_list]
            if recent_to_show:
                st.markdown("<div style='font-size:0.72rem; color:var(--text-secondary); margin-top:8px;'>Quick Re-Add Recent:</div>", unsafe_allow_html=True)
                rec_cols = st.columns(min(len(recent_to_show), 6))
                for idx, rkw in enumerate(recent_to_show[:6]):
                    c_idx = idx % min(len(recent_to_show), 6)
                    if rec_cols[c_idx].button(f"+ {rkw}", key=f"add_rec_kw_{idx}_{rkw}", disabled=inputs_disabled):
                        st.session_state.kw_list.append(rkw)
                        st.rerun()

        with tab_cfg_limits:
            cfg_l1, cfg_l2, cfg_l3, cfg_l4 = st.columns(4)
            with cfg_l1:
                max_limit = st.number_input("Limit Count", min_value=1, max_value=10000, value=1000, step=50, disabled=inputs_disabled)
            with cfg_l2:
                stop_mode_sel = st.selectbox("Stop Goal", ["Total Scanned", "Qualified Goal"], index=0, disabled=inputs_disabled)
            with cfg_l3:
                crawl_depth = st.number_input("Crawl Depth", min_value=1, max_value=2, value=1, step=1, disabled=inputs_disabled)
            with cfg_l4:
                match_logic = st.selectbox("Matching Logic", ["OR", "AND"], index=0, disabled=inputs_disabled)

        with tab_cfg_filters:
            cfg_f1, cfg_f2, cfg_f3 = st.columns(3)
            with cfg_f1:
                min_followers = st.number_input("Min Followers", min_value=0, value=0, step=100, disabled=inputs_disabled)
            with cfg_f2:
                max_followers = st.number_input("Max Followers (0=Unlimited)", min_value=0, value=0, step=1000, disabled=inputs_disabled)
            with cfg_f3:
                st.markdown("<div style='margin-top: 28px;'></div>", unsafe_allow_html=True)
                include_private = st.checkbox("Include Private Profiles", value=True, disabled=inputs_disabled)

        with tab_cfg_neg:
            def on_add_neg_kw():
                val = st.session_state.get("neg_kw_input_field", "").strip()
                if val:
                    if "," in val:
                        parts = [k.strip().lower() for k in val.split(",") if k.strip()]
                    else:
                        parts = [val.lower()]
                    for p in parts:
                        if p not in st.session_state.neg_kw_list:
                            st.session_state.neg_kw_list.append(p)
                    st.session_state["neg_kw_input_field"] = ""

            st.text_input("Exclude Keyword (Blacklist)", placeholder="Add blacklist words (e.g. crypto, agency)...", key="neg_kw_input_field", on_change=on_add_neg_kw, disabled=inputs_disabled)
            
            if st.session_state.neg_kw_list:
                st.markdown("<div style='font-size:0.75rem; color:#F87171; font-weight:600; margin-top:4px;'>Active Blacklist Words:</div>", unsafe_allow_html=True)
                neg_chip_cols = st.columns(min(len(st.session_state.neg_kw_list), 6))
                for idx, kw in enumerate(list(st.session_state.neg_kw_list)):
                    c_idx = idx % min(len(st.session_state.neg_kw_list), 6)
                    if neg_chip_cols[c_idx].button(f"🚫 {kw} ✖", key=f"del_neg_kw_{idx}_{kw}", disabled=inputs_disabled, help=f"Click to remove '{kw}'"):
                        st.session_state.neg_kw_list.remove(kw)
                        st.rerun()
                
                if st.button("Clear Blacklist", key="clr_neg_kws", disabled=inputs_disabled):
                    st.session_state.neg_kw_list = []
                    st.rerun()

    # SECONDARY CONTROLS TOOLBAR
    ctrl_col1, ctrl_col2, ctrl_col3, ctrl_col4 = st.columns([1, 1, 1, 1])
    with ctrl_col1:
        if st.session_state.is_running:
            if not st.session_state.is_paused:
                if st.button("⏸ Pause Search", use_container_width=True):
                    st.session_state.is_paused = True
                    if st.session_state.engine:
                        st.session_state.engine.is_paused = True
                    st.rerun()
            else:
                st.button("⏸ Paused", use_container_width=True, disabled=True)
        else:
            st.button("⏸ Pause Search", use_container_width=True, disabled=True)

    with ctrl_col2:
        if st.button("⏹ Stop Search", use_container_width=True, disabled=not st.session_state.is_running):
            if st.session_state.engine:
                st.session_state.engine.is_running = False
                st.session_state.engine.is_paused = False
            st.session_state.is_running = False
            st.session_state.is_paused = False
            st.rerun()

    with ctrl_col3:
        if st.button("🗑️ Clear All Data", use_container_width=True, disabled=st.session_state.is_running):
            clear_database()
            st.session_state.selected_usernames.clear()
            st.rerun()

    with ctrl_col4:
        if st.button("🔄 Refresh Data", use_container_width=True):
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
        session_options["🌐 All Searches Combined"] = "ALL"

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
        <div class="stat-num" style="color: #34D399;">{counts['qualified']:,}</div>
        <div class="stat-title">Qualified Leads</div>
    </div>
    <div class="stat-item">
        <div class="stat-num" style="color: #FBBF24;">{counts['doubtful']:,}</div>
        <div class="stat-title">Needs Review</div>
    </div>
    <div class="stat-item">
        <div class="stat-num" style="color: #FCA5A5;">{counts['unqualified']:,}</div>
        <div class="stat-title">Unqualified</div>
    </div>
    <div class="stat-item">
        <div class="stat-num" style="color: #818CF8;">{counts['contacts']:,}</div>
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
f_col1, f_col2, f_col3, f_col4, f_col5, f_col6 = st.columns([2, 1, 1, 0.9, 0.9, 0.9])

with f_col1:
    search_query = st.text_input("Search Filter", placeholder="Search username, bio, email, phone, or keyword...", label_visibility="collapsed")
with f_col2:
    min_match_score = st.number_input("Min Match Score (%)", min_value=0, max_value=100, value=0, step=5, label_visibility="collapsed")
with f_col3:
    category_filter_sel = st.selectbox("Category Filter", ["All Categories", "Qualified", "Needs Review", "Unqualified"], index=0, label_visibility="collapsed")
with f_col4:
    has_contact_check = st.checkbox("With Email/Phone Only", value=False)

cat_db_param = None
if category_filter_sel == "Qualified":
    cat_db_param = "QUALIFIED"
elif category_filter_sel == "Needs Review":
    cat_db_param = "DOUBTFUL"
elif category_filter_sel == "Unqualified":
    cat_db_param = "UNQUALIFIED"

filtered_accounts = get_filtered_accounts(
    category_filter=cat_db_param,
    min_score=float(min_match_score),
    search_query=search_query,
    has_contact_only=has_contact_check,
    search_id=active_search_id
)

# Export Data Generators
df_export = pd.DataFrame(filtered_accounts)
if not df_export.empty:
    export_cols = [c for c in ["username", "full_name", "category", "match_score", "email", "phone", "matched_keywords", "follower_count", "following_count", "bio", "is_private", "reason"] if c in df_export.columns]
    df_export = df_export[export_cols]

with f_col5:
    if not df_export.empty:
        csv_bytes = df_export.to_csv(index=False).encode('utf-8')
        st.download_button("📥 Export CSV", data=csv_bytes, file_name="instagram_leads.csv", mime="text/csv", use_container_width=True)
    else:
        st.button("📥 Export CSV", disabled=True, use_container_width=True)

with f_col6:
    if not df_export.empty:
        buffer = io.BytesIO()
        with pd.ExcelWriter(buffer, engine='openpyxl') as writer:
            df_export.to_excel(writer, index=False, sheet_name='Instagram Leads')
        excel_bytes = buffer.getvalue()
        st.download_button("📊 Export Excel", data=excel_bytes, file_name="instagram_leads.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", use_container_width=True)
    else:
        st.button("📊 Export Excel", disabled=True, use_container_width=True)

st.markdown("---")

# ---------------------------------------------------------
# 6. MODAL DIALOGS (DETAILS, OUTREACH PITCH, DELETION)
# ---------------------------------------------------------
@st.dialog("Direct Message Pitch Generator")
def show_outreach_pitch_dialog(acc):
    st.markdown(f"### 💬 Outreach Pitch for @{acc['username']}")
    name = acc['full_name'] or acc['username']
    matched_kws = acc['matched_keywords'] or 'your profile'
    
    pitch_style = st.selectbox("Pitch Style", ["Professional Collaboration", "Casual Sales DM", "Value First Offer"])
    
    if pitch_style == "Professional Collaboration":
        pitch_text = f"Hey {name}! 👋 I noticed your profile and your awesome work around {matched_kws}. I love what you're building! Would love to connect and discuss potential synergies or collaborations. Let me know if you're open to a quick chat!"
    elif pitch_style == "Casual Sales DM":
        pitch_text = f"Hi {name}! Came across your page while exploring top profiles in {matched_kws}. Impressive bio! We've helped creators & brands in your niche scale efficiently. Would you be open to seeing a 2-min breakdown of how?"
    else:
        pitch_text = f"Hey {name}, quick compliment on your page! Love your content on {matched_kws}. I put together some free growth insights specifically tailored for accounts like yours. Mind if I send it over here?"

    st.text_area("Generated DM Pitch", value=pitch_text, height=140)
    st.caption("Tip: Copy and paste this directly into your Instagram Direct Messages or Email outreach!")

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
    st.write(f"**Extracted Email:** `{acc.get('email') or 'None'}`")
    st.write(f"**Extracted Phone:** `{acc.get('phone') or 'None'}`")
    st.write(f"**Matched Keywords:** {acc['matched_keywords'] or 'None'}")
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
# 7. RESULTS LIST UI
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
        st.markdown("""
        <div style="background: rgba(30, 41, 59, 0.4); border: 1px dashed #334155; border-radius: 12px; padding: 24px; text-align: center; margin: 1.5rem 0;">
            <div style="font-size: 1.8rem; margin-bottom: 8px;">🎯</div>
            <div style="font-size: 1.05rem; font-weight: 700; color: #F8FAFC;">No Accounts Evaluated for this Search Session</div>
            <div style="font-size: 0.85rem; color: #94A3B8; margin-top: 4px;">
                Enter a <b>Target Username</b> & <b>Keywords</b> above, then click <b>▶️ Start Search</b> to begin scanning!
            </div>
        </div>
        """, unsafe_allow_html=True)
        return

    b_col1, b_col2 = st.columns([3, 1])
    with b_col2:
        num_sel = len(st.session_state.selected_usernames)
        if st.button(f"Delete Selected ({num_sel})", disabled=num_sel == 0, key=f"btn_del_sel_{tab_key}", use_container_width=True):
            confirm_batch_delete_dialog(list(st.session_state.selected_usernames))

    for acc in accounts_list:
        cat = acc["category"]
        if cat == "QUALIFIED":
            badge_html = '<span class="badge badge-qualified">🟢 Qualified</span>'
        elif cat == "DOUBTFUL":
            badge_html = '<span class="badge badge-review">🟡 Needs Review</span>'
        else:
            badge_html = '<span class="badge badge-unqualified">🔴 Unqualified</span>'

        score_val = acc.get("match_score", 0.0)
        bio_preview = (acc['bio'][:110] + "...") if acc['bio'] and len(acc['bio']) > 110 else (acc['bio'] or "No bio preview")
        
        contact_badges = ""
        if acc.get("email"):
            contact_badges += f'<span class="badge badge-contact">✉️ {acc["email"]}</span> '
        if acc.get("phone"):
            contact_badges += f'<span class="badge badge-contact">📞 {acc["phone"]}</span> '

        with st.container():
            c_check, c_info, c_actions = st.columns([0.3, 3.8, 1.8])
            
            with c_check:
                is_selected = acc['username'] in st.session_state.selected_usernames
                chk = st.checkbox(f"Select @{acc['username']}", value=is_selected, key=f"chk_{tab_key}_{acc['username']}", label_visibility="collapsed")
                if chk:
                    st.session_state.selected_usernames.add(acc['username'])
                else:
                    st.session_state.selected_usernames.discard(acc['username'])

            with c_info:
                st.markdown(
                    f"**@{acc['username']}** &nbsp; "
                    f"<span style='color:#94A3B8;'>({acc['full_name'] or 'No Name'})</span> &nbsp; "
                    f"{badge_html} &nbsp; {contact_badges}"
                    f"<span style='font-size:0.8rem; color:#818CF8; font-weight:600;'>Match: {score_val:.0f}%</span>", 
                    unsafe_allow_html=True
                )
                st.caption(f"Bio: {bio_preview} | Followers: {acc['follower_count']:,} | Matched: {acc['matched_keywords'] or 'None'}")

            with c_actions:
                ac1, ac2, ac3 = st.columns([1, 1, 1.2])
                with ac1:
                    if st.button("Details", key=f"det_{tab_key}_{acc['username']}", use_container_width=True):
                        show_account_details_dialog(acc)
                with ac2:
                    if st.button("Delete", key=f"del_{tab_key}_{acc['username']}", use_container_width=True):
                        delete_account(acc['username'])
                        st.session_state.selected_usernames.discard(acc['username'])
                        st.rerun()
                with ac3:
                    if st.button("💬 DM Pitch", key=f"pitch_{tab_key}_{acc['username']}", use_container_width=True):
                        show_outreach_pitch_dialog(acc)

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
        st.code("\n".join(st.session_state.engine.logs[-200:]), language="text")
    else:
        st.info("Agent is idle. Start search to view activity logs.")

# Sync state
if st.session_state.engine:
    st.session_state.is_running = st.session_state.engine.is_running
    st.session_state.is_paused = st.session_state.engine.is_paused
