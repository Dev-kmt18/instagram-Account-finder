from insta_bot.database import (
    init_db, save_account, get_counts, get_all_accounts, clear_database,
    update_account_category, delete_account, get_filtered_accounts,
    save_search_history, get_search_history, delete_search_history_item,
    get_pending_queue_count, add_to_queue,
    add_reel_log, get_reel_logs, clear_reel_logs, is_reel_already_sent,
    add_scheduled_task, get_pending_scheduled_tasks, update_scheduled_task_status,
    get_all_scheduled_tasks, delete_scheduled_task, clear_scheduled_tasks
)

from insta_bot.classifier import evaluate_account
from insta_bot.reel_bot import parse_time_str, ReelAutomationEngine

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
    clear_reel_logs()
    
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
    clear_database()
    print("✅ Search History Persistence Test Passed!")

def test_reel_automation_db_and_utils():
    init_db()
    clear_reel_logs()
    clear_scheduled_tasks()

    # 1. Test time parsing utility

    h1, m1 = parse_time_str("09:00 PM")
    assert (h1, m1) == (21, 0), f"Expected (21, 0), got ({h1}, {m1})"

    h2, m2 = parse_time_str("9:30 AM")
    assert (h2, m2) == (9, 30), f"Expected (9, 30), got ({h2}, {m2})"

    h3, m3 = parse_time_str("23:15")
    assert (h3, m3) == (23, 15), f"Expected (23, 15), got ({h3}, {m3})"
    print("✅ Time Parser Unit Tests Passed!")

    # 2. Test Reel Logs DB & Duplicate Detection
    add_reel_log("friend1", "https://instagram.com/reel/123", "SENT", "Successfully sent Reel to @friend1")
    logs = get_reel_logs(limit=10)
    assert len(logs) == 1
    assert logs[0]["recipient"] == "friend1"
    assert logs[0]["status"] == "SENT"

    # Test Duplicate Check
    assert is_reel_already_sent("friend1", "https://instagram.com/reel/123") == True
    assert is_reel_already_sent("friend1", "https://instagram.com/reel/999") == False
    assert is_reel_already_sent("other_user", "https://instagram.com/reel/123") == False
    print("✅ Reel Log DB & Duplicate Detection Unit Tests Passed!")

    clear_reel_logs()
    assert len(get_reel_logs()) == 0


    # 3. Test Scheduled Tasks DB
    t_id = add_scheduled_task(
        sessionid="test_sess_id",
        recipients="user1, user2",
        reel_urls="https://instagram.com/reel/abc",
        total_reels=10,
        start_time="09:00 PM",
        end_time="11:00 PM"
    )
    pending = get_pending_scheduled_tasks()
    assert len(pending) == 1
    assert pending[0]["id"] == t_id
    assert pending[0]["status"] == "SCHEDULED"

    update_scheduled_task_status(t_id, "COMPLETED")
    pending_after = get_pending_scheduled_tasks()
    assert len(pending_after) == 0

    all_tasks = get_all_scheduled_tasks()
    assert len(all_tasks) == 1
    assert all_tasks[0]["status"] == "COMPLETED"

    delete_scheduled_task(t_id)
    assert len(get_all_scheduled_tasks()) == 0
    print("✅ Reel Scheduler DB Tasks Tests Passed!")

    # 4. Reel engine verify session invalid test
    eng = ReelAutomationEngine("invalid_sessionid")
    is_valid, user, msg = eng.verify_sessionid()
    assert not is_valid, "Expected invalid session to fail verification"
    print("✅ Reel Engine Session Verification Validation Passed!")

if __name__ == "__main__":
    test_classifier()
    test_database()
    test_reel_automation_db_and_utils()
    print("🎉 All updated full-stack tests passed successfully!")

