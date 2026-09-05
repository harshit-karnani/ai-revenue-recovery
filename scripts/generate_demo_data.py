import os
import sys
import uuid
import datetime
from sqlalchemy.orm import Session

# Ensure app is in path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app.core.database import SessionLocal
from app.services.payment_simulator import PaymentSimulator
from app.models.transaction import Transaction
from app.models.payment_attempt import PaymentAttempt
from app.core.regulatory_rules import IST_TZ

def run_generate():
    db = SessionLocal()
    try:
        simulator = PaymentSimulator(seed=123)
        events = simulator.generate_events(count=300)
        
        inserted_tx = 0
        inserted_attempts = 0
        
        for ev in events:
            # Create a unique transaction ID for idempotency (we could use deterministic uuids based on seed)
            tx_id = str(uuid.uuid4())
            
            # Create transaction
            tx = Transaction(
                id=tx_id,
                amount=ev["amount"],
                currency=ev["currency"],
                payment_type=ev["payment_type"],
                subscription_category=ev["subscription_category"],
                mandate_status=ev["mandate_status"],
                customer_id=str(uuid.uuid4()),
                status="failed",
                created_at=datetime.datetime.now(IST_TZ),
                updated_at=datetime.datetime.now(IST_TZ)
            )
            db.add(tx)
            inserted_tx += 1
            
            # Create payment attempt
            attempt = PaymentAttempt(
                transaction_id=tx_id,
                attempt_number=ev["attempt_count"],
                status="failed",
                decline_code=ev["decline_code"] or ev["expected_failure_code"], # For simulator ground truth reference in DB
                error_message=f"Simulated {ev['expected_bucket']} failure",
                executed_at=ev["current_time"]
            )
            db.add(attempt)
            inserted_attempts += 1
            
        db.commit()
        print(f"Generated and inserted {inserted_tx} transactions and {inserted_attempts} attempts.")
        
    except Exception as e:
        db.rollback()
        print(f"Error during generation: {e}")
    finally:
        db.close()

if __name__ == "__main__":
    run_generate()
