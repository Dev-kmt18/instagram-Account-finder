from insta_bot.database import (
    init_db, save_account, get_counts, get_all_accounts, clear_database,
    update_account_category, delete_account, get_filtered_accounts,
    save_search_history, get_search_history, delete_search_history_item,
    get_pending_queue_count, add_to_queue
)
from insta_bot.classifier import evaluate_account

def test_classifier():
    keywords = ["fitness", "coach", "gym", "trainer"]
    neg_keywords = ["crypto", "agency", "bot"]
    
    # Test case 1: Qualified with contact info (Email & Phone)
    cat1, kw1, r1, score1, email1, phone1 = evaluate_account(
        "john_fitness", "John Doe", "Online Fitness Coach & Gym Trainer | DM for coaching john@fit.com +1 234 567 8900",
        keywords, negative_keywords=neg_keywords, match_logic="OR"
    )
    assert cat1 == "QUALIFIED", f"Expected QUALIFIED, got {cat1}"
    assert score1 == 100.0, f"Expected score 100.0, got {score1}"
    assert email1 == "john@fit.com", f"Expected john@fit.com, got {email1}"
    assert "+1 234 567 8900" in phone1, f"Expected phone in {phone1}"
    print("✅ Classifier Test 1 (Qualified + Contacts) Passed!")

    # Test case 2: Blacklist / Exclusion Keyword Disqualification
    cat2, kw2, r2, score2, email2, phone2 = evaluate_account(
        "crypto_fit", "Crypto Fitness Bot", "Online Fitness Coach & Crypto trader",
        keywords, negative_keywords=neg_keywords, match_logic="OR"
    )
    assert cat2 == "UNQUALIFIED", f"Expected UNQUALIFIED due to crypto, got {cat2}"
    assert "Disqualified by negative keyword" in r2
    print("✅ Classifier Test 2 (Blacklist Disqualification) Passed!")

    # Test case 3: AND Logic Mode (Fail case)
    cat3, kw3, r3, score3, email3, phone3 = evaluate_account(
        "john_gym", "John Smith", "Fitness enthusiast and lifter",
        keywords=["fitness", "coach"], negative_keywords=[], match_logic="AND"
    )
    assert cat3 == "UNQUALIFIED", f"Expected UNQUALIFIED for missing 'coach', got {cat3}"
    print("✅ Classifier Test 3 (AND Logic Mode) Passed!")

def test_database():
    init_db()
    clear_database()
    
    # Save dummy accounts with contact info
    save_account("101", "fitness_john", "John Gym", "Fitness Trainer contact: john@fit.com", False, "QUALIFIED", ["fitness"], "Exact match", match_score=100.0, email="john@fit.com", phone="+123456789")
    save_account("102", "doubtful_user", "Sam P", "Fitnes lover", True, "DOUBTFUL", ["fitness (65%)"], "Fuzzy match", match_score=65.0)
    save_account("103", "tech_guy", "Bob Dev", "Python Dev", False, "UNQUALIFIED", [], "No match", match_score=0.0)

    counts = get_counts()
    assert counts["total"] == 3, f"Expected 3, got {counts['total']}"
    assert counts["qualified"] == 1
    assert counts["contacts"] == 1
    print("✅ Database Baseline & Contacts Count Passed:", counts)

    # Test queue resume count
    add_to_queue("999", "pending_user", 1)
    pending_cnt = get_pending_queue_count()
    assert pending_cnt == 1, f"Expected 1 pending item, got {pending_cnt}"
    print("✅ Queue Resume Count Test Passed!")

    # Test search history
    hid = save_search_history("target_acc", ["fitness"], "followers", 100, 1, "RUNNING", 10, 5)
    history = get_search_history()
    assert len(history) == 1
    delete_search_history_item(hid)
    print("✅ Search History Persistence Test Passed!")

if __name__ == "__main__":
    test_classifier()
    test_database()
    print("🎉 All updated full-stack tests passed successfully!")
