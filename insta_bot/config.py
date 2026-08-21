import os

# Base paths
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(BASE_DIR, "insta_agent.db")
SESSION_FILE = os.path.join(BASE_DIR, "session.json")
EXPORTS_DIR = os.path.join(BASE_DIR, "exports")

# Anti-Bot Rate Limiting & Delays (in seconds)
MIN_DELAY_PER_PROFILE = 1.0
MAX_DELAY_PER_PROFILE = 2.5

# Batch Cool-down settings
BATCH_SIZE = 50          # Accounts processed before cool-down
COOL_DOWN_MIN_SEC = 5    # 5 seconds cool-down
COOL_DOWN_MAX_SEC = 15   # 15 seconds cool-down


# Classification Thresholds (Fuzzy matching 0-100)
QUALIFIED_SCORE_THRESHOLD = 80
DOUBTFUL_SCORE_THRESHOLD = 45
