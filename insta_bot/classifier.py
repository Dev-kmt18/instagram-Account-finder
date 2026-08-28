import re
from typing import List, Dict, Tuple, Optional
from rapidfuzz import fuzz
from insta_bot.config import QUALIFIED_SCORE_THRESHOLD, DOUBTFUL_SCORE_THRESHOLD

# Regex patterns for contact extraction
EMAIL_REGEX = re.compile(
    r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}', 
    re.IGNORECASE
)

# Broad international and local phone/WhatsApp pattern
PHONE_REGEX = re.compile(
    r'(?:(?:wa\.me\/|whatsapp|ph|phone|call|contact|tel|mob|mobile|📲|📞|📱|💬)?\s*[:\-\s]?)?'
    r'(\+?\d{1,3}[\s\.\-]?)?\(?\d{2,5}\)?[\s\.\-]?\d{3,5}[\s\.\-]?\d{3,5}',
    re.IGNORECASE
)

def normalize_text(text: str) -> str:
    if not text:
        return ""
    text = text.lower()
    return " ".join(text.split())

def extract_contacts(bio: str, name: str = "", username: str = "") -> Tuple[str, str]:
    """Extract email and phone/WhatsApp numbers from user bio and metadata."""
    combined = f"{bio} {name} {username}"
    
    # 1. Email Extraction
    emails = EMAIL_REGEX.findall(combined)
    clean_emails = []
    for e in emails:
        e_clean = e.strip().rstrip(".,;")
        # Exclude common image extensions or invalid tokens falsely matched
        if not any(e_clean.endswith(ext) for ext in [".png", ".jpg", ".jpeg", ".webp", ".svg"]):
            clean_emails.append(e_clean)
    email_str = ", ".join(list(dict.fromkeys(clean_emails)))

    # 2. Phone Extraction
    phones = []
    # Search bio line by line to reduce false positives
    for line in combined.split("\n"):
        for match in PHONE_REGEX.finditer(line):
            phone_raw = match.group(0).strip()
            digits_only = re.sub(r'\D', '', phone_raw)
            # Valid phone number length filter (7 to 15 digits)
            if 7 <= len(digits_only) <= 15:
                # Avoid capturing standalone small numbers or follower counts
                if not re.match(r'^\d{1,4}$', digits_only):
                    phones.append(phone_raw)

    # Format unique phones
    phone_str = ", ".join(list(dict.fromkeys(phones[:2]))) # limit to top 2 numbers
    return email_str, phone_str

def evaluate_account(
    username: str,
    full_name: str,
    bio: str,
    keywords: List[str],
    negative_keywords: Optional[List[str]] = None,
    match_logic: str = "OR" # "OR" or "AND"
) -> Tuple[str, List[str], str, float, str, str]:
    """
    Evaluates an Instagram profile against target keywords, exclusion rules, and contact extraction.
    Returns: (category, matched_keywords, reason, match_score, email, phone)
    Categories: QUALIFIED (🟢), DOUBTFUL (🟡), UNQUALIFIED (🔴)
    """
    negative_keywords = negative_keywords or []
    email, phone = extract_contacts(bio, full_name, username)

    norm_username = normalize_text(username)
    norm_name = normalize_text(full_name)
    norm_bio = normalize_text(bio)
    combined_text = f"{norm_username} {norm_name} {norm_bio}"
    words_in_text = re.findall(r'\w+', combined_text)

    # 1. Exclusion / Negative Keyword Filter
    if negative_keywords:
        for nkw in negative_keywords:
            clean_nkw = normalize_text(nkw)
            if not clean_nkw:
                continue
            pattern = r'\b' + re.escape(clean_nkw) + r'\b'
            if re.search(pattern, combined_text) or clean_nkw in norm_username:
                return (
                    "UNQUALIFIED",
                    [],
                    f"Disqualified by negative keyword: '{nkw}'",
                    0.0,
                    email,
                    phone
                )

    if not keywords:
        return "UNQUALIFIED", [], "No keywords provided for search", 0.0, email, phone

    matched_exact = []
    matched_fuzzy = []
    individual_scores = []

    for kw in keywords:
        clean_kw = normalize_text(kw)
        if not clean_kw:
            continue

        kw_matched = False
        kw_best_score = 0.0

        # Exact Word / Boundary Match
        pattern = r'\b' + re.escape(clean_kw) + r'\b'
        if re.search(pattern, combined_text) or clean_kw in norm_username:
            matched_exact.append(kw)
            kw_best_score = 100.0
            kw_matched = True
        else:
            # Word-level Fuzzy Match
            for w in words_in_text:
                if len(w) >= 3:
                    score = fuzz.ratio(clean_kw, w)
                    if score > kw_best_score:
                        kw_best_score = score

            if kw_best_score >= QUALIFIED_SCORE_THRESHOLD:
                matched_fuzzy.append(kw)
                kw_matched = True
            elif kw_best_score >= DOUBTFUL_SCORE_THRESHOLD:
                matched_fuzzy.append(f"{kw} ({kw_best_score:.0f}%)")
                kw_matched = True

        individual_scores.append(kw_best_score)

    all_matched = list(dict.fromkeys(matched_exact + matched_fuzzy))
    max_score = max(individual_scores) if individual_scores else 0.0

    # Logic Mode: AND Requirements vs OR Requirements
    if match_logic.upper() == "AND":
        # Every target keyword must have matched at least at DOUBTFUL score threshold
        passed_all = len(all_matched) == len(keywords)
        if not passed_all:
            return (
                "UNQUALIFIED",
                all_matched,
                f"AND condition failed (Matched {len(all_matched)}/{len(keywords)} keywords)",
                0.0,
                email,
                phone
            )

    # Categorization Decision
    if matched_exact:
        contact_note = " [Contacts Found]" if (email or phone) else ""
        return (
            "QUALIFIED", 
            all_matched, 
            f"Exact keyword match: {', '.join(matched_exact)}{contact_note}",
            100.0 if not max_score else float(max_score),
            email,
            phone
        )
    
    if all_matched and max_score >= QUALIFIED_SCORE_THRESHOLD:
        return (
            "QUALIFIED", 
            all_matched, 
            f"High confidence match ({max_score:.0f}%)",
            float(max_score),
            email,
            phone
        )
    
    if all_matched and max_score >= DOUBTFUL_SCORE_THRESHOLD:
        return (
            "DOUBTFUL", 
            all_matched, 
            f"Partial match detected ({max_score:.0f}% confidence)",
            float(max_score),
            email,
            phone
        )

    return (
        "UNQUALIFIED", 
        [], 
        "No matching keywords found in profile bio or handle",
        0.0,
        email,
        phone
    )
