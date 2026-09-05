import random
import datetime
from typing import Dict, Any, List
from app.core.regulatory_rules import IST_TZ

class PaymentSimulator:
    def __init__(self, seed: int = 42):
        self.rng = random.Random(seed)
        
    def generate_events(self, count: int) -> List[Dict[str, Any]]:
        events = []
        for _ in range(count):
            bucket_choice = self.rng.choices(["A", "B", "C"], weights=[40, 30, 30])[0]
            if bucket_choice == "A":
                events.append(self._generate_bucket_a())
            elif bucket_choice == "B":
                events.append(self._generate_bucket_b())
            else:
                events.append(self._generate_bucket_c())
        return events

    def _generate_bucket_a(self) -> Dict[str, Any]:
        failure_codes = ["insufficient_funds", "expired_card", "invalid_card", "card_blocked"]
        code = self.rng.choice(failure_codes)
        
        now = datetime.datetime.now(IST_TZ)
        amount = round(self.rng.uniform(100, 10000), 2)
        
        return {
            "amount": amount,
            "currency": "INR",
            "payment_type": "card",
            "subscription_category": "ecommerce_subscription",
            "notification_sent_at": now - datetime.timedelta(hours=25), # Valid pre-debit
            "scheduled_at": now.replace(hour=14), # Valid execution window
            "current_time": now.replace(hour=14),
            "attempt_count": self.rng.randint(1, 3), # Valid retry cap
            "mandate_status": "active",
            "authentication_status": "not_authenticated",
            "decline_code": code,
            "expected_bucket": "A",
            "expected_failure_code": code
        }

    def _generate_bucket_b(self) -> Dict[str, Any]:
        failure_codes = ["generic_decline", "do_not_honor", "processing_error", "timeout"]
        code = self.rng.choice(failure_codes)
        
        now = datetime.datetime.now(IST_TZ)
        amount = round(self.rng.uniform(100, 10000), 2)
        
        # Introduce deliberate contextual ambiguity for ML testing
        # If it's generic_decline and amount > 5000 and attempt_count == 3, it's actually Bucket A (in real life)
        is_ambiguous_a = False
        attempt = self.rng.randint(1, 3)
        if code in ["generic_decline", "processing_error"] and self.rng.random() < 0.3:
            # force an overlap scenario
            amount = round(self.rng.uniform(5000, 10000), 2)
            attempt = 3
            is_ambiguous_a = True
            
        return {
            "amount": amount,
            "currency": "INR",
            "payment_type": self.rng.choice(["card", "upi_autopay"]),
            "subscription_category": "other",
            "notification_sent_at": now - datetime.timedelta(hours=25), # Valid pre-debit
            "scheduled_at": now.replace(hour=14), # Valid execution window
            "current_time": now.replace(hour=14),
            "attempt_count": attempt,
            "mandate_status": "active",
            "authentication_status": "not_authenticated",
            "decline_code": code,
            "expected_bucket": "A" if is_ambiguous_a else "B",
            "expected_failure_code": code
        }

    def _generate_bucket_c(self) -> Dict[str, Any]:
        regulatory_cases = ["pre_debit", "afa", "execution_window", "mandate_expired"]
        case = self.rng.choice(regulatory_cases)
        
        now = datetime.datetime.now(IST_TZ)
        
        event = {
            "amount": round(self.rng.uniform(100, 5000), 2),
            "currency": "INR",
            "payment_type": "upi_autopay",
            "subscription_category": "ecommerce_subscription",
            "notification_sent_at": now - datetime.timedelta(hours=25),
            "scheduled_at": now.replace(hour=14),
            "current_time": now.replace(hour=14),
            "attempt_count": self.rng.randint(1, 3),
            "mandate_status": "active",
            "authentication_status": "not_authenticated",
            "decline_code": None, # Regulatory failures usually don't need a decline_code in our schema!
            "expected_bucket": "C"
        }
        
        if case == "pre_debit":
            # 23h elapsed or 23h59m
            hours_elapsed = self.rng.choice([23, 23.98])
            event["notification_sent_at"] = now - datetime.timedelta(hours=hours_elapsed)
            event["expected_failure_code"] = "missed_predebit_notification"
            
        elif case == "afa":
            # Trigger AFA with amount > 15000
            event["amount"] = self.rng.choice([15000.01, 16000, 25000])
            event["expected_failure_code"] = "afa_reauth_required"
            
        elif case == "execution_window":
            # Trigger execution window 10:00 - 13:00
            event["scheduled_at"] = now.replace(hour=self.rng.choice([10, 11, 12]), minute=0)
            event["current_time"] = event["scheduled_at"]
            event["expected_failure_code"] = "execution_window_block"
            
        elif case == "mandate_expired":
            event["mandate_status"] = "expired"
            event["expected_failure_code"] = "mandate_expired"
            
        return event
