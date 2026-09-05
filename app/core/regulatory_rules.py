import datetime
import zoneinfo

PRE_DEBIT_REQUIRED_HOURS = 24
DEFAULT_AFA_LIMIT_INR = 15000
EXCEPTION_AFA_LIMIT_INR = 100000
MAX_TOTAL_ATTEMPTS = 4
TIMEZONE_STR = "Asia/Kolkata"
IST_TZ = zoneinfo.ZoneInfo(TIMEZONE_STR)

EXECUTION_BLOCK_START = datetime.time(10, 0)
EXECUTION_BLOCK_END = datetime.time(13, 0)
AFTERNOON_VALID_START = datetime.time(13, 0)
AFTERNOON_VALID_END = datetime.time(17, 0)
NIGHT_VALID_START = datetime.time(21, 30)

AFA_EXCEPTION_CATEGORIES = {
    "mutual_fund",
    "mutual_fund_sip",
    "insurance_premium",
    "credit_card_bill",
}
