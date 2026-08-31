import time
import datetime
import threading
import sys
import os
from typing import Optional, List, Dict

from insta_bot.database import (
    init_db,
    get_pending_scheduled_tasks,
    update_scheduled_task_status,
    add_reel_log
)
from insta_bot.reel_bot import ReelAutomationEngine, parse_time_str

class ReelSchedulerDaemon:
    def __init__(self):
        self.is_running = False
        self.thread: Optional[threading.Thread] = None
        self.active_engine: Optional[ReelAutomationEngine] = None
        self.current_task_id: Optional[int] = None

    def log(self, msg: str):
        ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        formatted = f"🤖 [BACKGROUND DAEMON {ts}] {msg}"
        print(formatted)
        add_reel_log(recipient="DAEMON", reel_url="", status="INFO", message=msg)

    def check_and_execute_tasks(self):
        """Poll SQLite database for pending scheduled reel automation tasks."""
        pending_tasks = get_pending_scheduled_tasks()
        if not pending_tasks:
            return

        now = datetime.datetime.now()
        current_hm = now.strftime("%H:%M")

        for task in pending_tasks:
            if not self.is_running:
                break

            task_id = task["id"]
            start_time = task["start_time"] or "21:00"
            end_time = task["end_time"] or "23:00"

            # Parse start time comparison (12h AM/PM or 24h format)
            try:
                sh, sm = parse_time_str(start_time)
                eh, em = parse_time_str(end_time)
                start_dt = now.replace(hour=sh, minute=sm, second=0, microsecond=0)
                end_dt = now.replace(hour=eh, minute=em, second=0, microsecond=0)
                if end_dt <= start_dt:
                    end_dt += datetime.timedelta(days=1)
            except Exception:
                start_dt = now
                end_dt = now + datetime.timedelta(hours=2)

            # Check if current time is inside or after scheduled start time
            should_run = (now >= start_dt and now <= end_dt) or (abs((now - start_dt).total_seconds()) < 600)

            if should_run:
                self.log(f"⏰ Executing Scheduled Task #{task_id} (Window: {start_time} - {end_time})...")
                update_scheduled_task_status(task_id, "RUNNING")
                self.current_task_id = task_id

                # Parse recipients and URLs
                recipients = [r.strip().lstrip("@") for r in task["recipients"].split(",") if r.strip()]
                urls = [u.strip() for u in task["reel_urls"].split("\n") if u.strip()]
                total_reels = task["total_reels"] or 15

                engine = ReelAutomationEngine(sessionid=task["sessionid"])
                self.active_engine = engine

                try:
                    engine.start_automation(
                        recipients=recipients,
                        reel_urls=urls,
                        total_reels=total_reels,
                        start_time_str=start_time,
                        end_time_str=end_time
                    )
                    
                    # Wait for engine thread to complete
                    while engine.is_running:
                        time.sleep(2)

                    if engine.status == "COMPLETED":
                        update_scheduled_task_status(task_id, "COMPLETED")
                        self.log(f"✅ Completed Task #{task_id}! Sent: {engine.sent_count} | Failed: {engine.failed_count}")
                    else:
                        update_scheduled_task_status(task_id, "CANCELLED")
                        self.log(f"⏹ Task #{task_id} stopped or cancelled (Status: {engine.status}).")
                except Exception as err:
                    update_scheduled_task_status(task_id, "FAILED")
                    self.log(f"❌ Error in Task #{task_id}: {err}")
                finally:
                    self.active_engine = None
                    self.current_task_id = None

    def start_daemon(self):
        """Start the background daemon loop in a daemon thread."""
        if self.is_running:
            self.log("Daemon is already running.")
            return

        self.is_running = True
        self.log("🚀 Starting 24/7 Standalone Background Reel Scheduler Daemon...")

        def loop():
            while self.is_running:
                try:
                    self.check_and_execute_tasks()
                except Exception as e:
                    self.log(f"Daemon exception loop: {e}")
                time.sleep(10)

        self.thread = threading.Thread(target=loop, daemon=True)
        self.thread.start()

    def stop_daemon(self):
        """Stop the background daemon loop."""
        self.is_running = False
        if self.active_engine:
            self.active_engine.stop_automation()
        self.log("⏹ Background Reel Scheduler Daemon STOPPED.")

# Global daemon instance singleton
_global_daemon_instance: Optional[ReelSchedulerDaemon] = None

def get_daemon_instance() -> ReelSchedulerDaemon:
    global _global_daemon_instance
    if _global_daemon_instance is None:
        _global_daemon_instance = ReelSchedulerDaemon()
    return _global_daemon_instance

if __name__ == "__main__":
    init_db()
    daemon = get_daemon_instance()
    daemon.start_daemon()
    print("🤖 Background Reel Scheduler Daemon active. Press Ctrl+C to exit.")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        daemon.stop_daemon()
        print("Daemon stopped.")
