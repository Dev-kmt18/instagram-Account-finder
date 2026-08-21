from insta_bot.database import (
    init_db, save_account, get_counts, get_all_accounts, clear_database,
    update_account_category, delete_account, get_filtered_accounts,
    save_search_history, get_search_history, delete_search_history_item
)
from insta_bot.classifier import evaluate_account

def test_classifier():
    keywords = ["fitness", "coach", "gym", "trainer"]
    
    # Test case 1: Qualified
    cat1, kw1, r1, score1 = evaluate_account("john_fitness", "John Doe", "Online Fitness Coach & Gym Trainer", keywords)
    assert cat1 == "QUALIFIED", f"Expected QUALIFIED, got {cat1}"
    assert score1 == 100.0, f"Expected score 100.0, got {score1}"
    print("✅ Classifier Test 1 (Qualified) Passed:", cat1, kw1, score1)

    # Test case 2: Doubtful
    cat2, kw2, r2, score2 = evaluate_account("fit_johnny", "Johnny", "Love fitnes and body building", keywords)
    assert cat2 in ["QUALIFIED", "DOUBTFUL"], f"Expected DOUBTFUL/QUALIFIED, got {cat2}"
    assert score2 > 0, f"Expected score > 0, got {score2}"
    print("✅ Classifier Test 2 (Doubtful) Passed:", cat2, kw2, score2)

    # Test case 3: Unqualified
    cat3, kw3, r3, score3 = evaluate_account("coder_alex", "Alex Smith", "Python Developer & Tech Enthusiast", keywords)
    assert cat3 == "UNQUALIFIED", f"Expected UNQUALIFIED, got {cat3}"
    assert score3 == 0.0, f"Expected score 0.0, got {score3}"
    print("✅ Classifier Test 3 (Unqualified) Passed:", cat3, kw3, score3)

def test_database():
    init_db()
    clear_database()
    
    # Save dummy accounts
    save_account("101", "fitness_john", "John Gym", "Fitness Trainer", False, "QUALIFIED", ["fitness"], "Exact match", match_score=100.0)
    save_account("102", "doubtful_user", "Sam P", "Fitnes lover", True, "DOUBTFUL", ["fitness (65%)"], "Fuzzy match", match_score=65.0)
    save_account("103", "tech_guy", "Bob Dev", "Python Dev", False, "UNQUALIFIED", [], "No match", match_score=0.0)

    counts = get_counts()
    assert counts["total"] == 3, f"Expected 3, got {counts['total']}"
    assert counts["qualified"] == 1
    assert counts["doubtful"] == 1
    assert counts["unqualified"] == 1
    assert counts["private"] == 1

    print("✅ Database Baseline Tests Passed:", counts)

    # Test filtering by match score (>50%)
    high_match = get_filtered_accounts(min_score=50.0)
    assert len(high_match) == 2, f"Expected 2 accounts >= 50% match score, got {len(high_match)}"
    print("✅ Match Score Filtering (>50%) Test Passed! Found:", len(high_match))

    # Test category update
    update_account_category("doubtful_user", "QUALIFIED")
    counts_updated = get_counts()
    assert counts_updated["qualified"] == 2
    assert counts_updated["doubtful"] == 0
    print("✅ Manual Review Category Update Passed:", counts_updated)

    # Test account deletion
    delete_account("tech_guy")
    counts_after_del = get_counts()
    assert counts_after_del["total"] == 2, f"Expected 2 accounts after deletion, got {counts_after_del['total']}"
    print("✅ Account Deletion Test Passed:", counts_after_del)

    # Test search history
    hid = save_search_history("target_acc", ["fitness", "gym"], "followers", 100, 1, "RUNNING", 10, 5)
    history = get_search_history()
    assert len(history) == 1, f"Expected 1 history item, got {len(history)}"
    assert history[0]["target_username"] == "target_acc"
    print("✅ Search History Persistence Test Passed:", history[0])

    delete_search_history_item(hid)
    assert len(get_search_history()) == 0
    print("✅ Search History Deletion Test Passed!")

if __name__ == "__main__":
    test_classifier()
    test_database()
    print("🎉 All core tests passed successfully!")

