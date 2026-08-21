import re
from typing import List, Dict, Tuple
from rapidfuzz import fuzz
from insta_bot.config import QUALIFIED_SCORE_THRESHOLD, DOUBTFUL_SCORE_THRESHOLD

def normalize_text(text: str) -> str:
    if not text:
        return ""
    text = text.lower()
    return " ".join(text.split())

def evaluate_account(
    username: str,
    full_name: str,
    bio: str,
    keywords: List[str]
) -> Tuple[str, List[str], str, float]:
    """
    Evaluates an Instagram profile against target keywords.
    Returns: (category, matched_keywords, reason, match_score)
    Categories: QUALIFIED (🟢), DOUBTFUL (🟡), UNQUALIFIED (🔴)
    """
    if not keywords:
        return "UNQUALIFIED", [], "No keywords provided for search", 0.0

    norm_username = normalize_text(username)
    norm_name = normalize_text(full_name)
    norm_bio = normalize_text(bio)
    combined_text = f"{norm_username} {norm_name} {norm_bio}"
    words_in_text = re.findall(r'\w+', combined_text)

    matched_exact = []
    matched_fuzzy = []
    max_fuzzy_score = 0.0

    for kw in keywords:
        clean_kw = normalize_text(kw)
        if not clean_kw:
            continue

        # 1. Exact Word Match / Boundary Match
        pattern = r'\b' + re.escape(clean_kw) + r'\b'
        if re.search(pattern, combined_text):
            matched_exact.append(kw)
            continue

        # Exact substring inside username or handle (e.g., @fitness_john)
        if clean_kw in norm_username:
            matched_exact.append(kw)
            continue

        # 2. Word-level Fuzzy Match
        best_word_score = 0.0
        for w in words_in_text:
            if len(w) >= 3:
                score = fuzz.ratio(clean_kw, w)
                if score > best_word_score:
                    best_word_score = score

        if best_word_score > max_fuzzy_score:
            max_fuzzy_score = best_word_score

        if best_word_score >= QUALIFIED_SCORE_THRESHOLD:
            matched_fuzzy.append(kw)
        elif best_word_score >= DOUBTFUL_SCORE_THRESHOLD:
            matched_fuzzy.append(f"{kw} ({best_word_score:.0f}%)")

    # Categorization Logic
    if matched_exact:
        return (
            "QUALIFIED", 
            matched_exact, 
            f"Exact keyword match found: {', '.join(matched_exact)}",
            100.0
        )
    
    if matched_fuzzy and max_fuzzy_score >= QUALIFIED_SCORE_THRESHOLD:
        return (
            "QUALIFIED", 
            matched_fuzzy, 
            f"High confidence fuzzy match ({max_fuzzy_score:.0f}%)",
            float(max_fuzzy_score)
        )
    
    if matched_fuzzy and max_fuzzy_score >= DOUBTFUL_SCORE_THRESHOLD:
        return (
            "DOUBTFUL", 
            matched_fuzzy, 
            f"Partial match detected ({max_fuzzy_score:.0f}% confidence) - review recommended",
            float(max_fuzzy_score)
        )

    return (
        "UNQUALIFIED", 
        [], 
        "No matching keywords found in bio, username, or name",
        0.0
    )

