from app.services.payment_simulator import PaymentSimulator

def test_simulator_reproducibility():
    sim1 = PaymentSimulator(seed=123)
    sim2 = PaymentSimulator(seed=123)
    
    events1 = sim1.generate_events(10)
    events2 = sim2.generate_events(10)
    
    def remove_times(events):
        for e in events:
            e.pop("notification_sent_at", None)
            e.pop("scheduled_at", None)
            e.pop("current_time", None)
        return events
        
    assert remove_times(events1) == remove_times(events2)

def test_simulator_different_seeds():
    sim1 = PaymentSimulator(seed=123)
    sim2 = PaymentSimulator(seed=456)
    
    events1 = sim1.generate_events(10)
    events2 = sim2.generate_events(10)
    
    assert events1 != events2

def test_simulator_distribution():
    sim = PaymentSimulator(seed=42)
    events = sim.generate_events(100)
    
    buckets = [e["expected_bucket"] for e in events]
    
    # We shouldn't strictly test exact counts for a random distribution, but we can verify all 3 exist
    assert "A" in buckets
    assert "B" in buckets
    assert "C" in buckets

def test_simulator_ground_truth_consistency():
    sim = PaymentSimulator(seed=42)
    events = sim.generate_events(100)
    
    for e in events:
        if e["expected_bucket"] == "A":
            # With overlap, ambiguous codes can be in A
            assert e["decline_code"] in ["insufficient_funds", "expired_card", "invalid_card", "card_blocked", "generic_decline", "processing_error"]
        elif e["expected_bucket"] == "B":
            assert e["decline_code"] in ["generic_decline", "do_not_honor", "processing_error", "timeout"]
        elif e["expected_bucket"] == "C":
            # For C, decline_code is usually null, we check expected_failure_code
            assert e["decline_code"] is None
            assert e["expected_failure_code"] in ["missed_predebit_notification", "afa_reauth_required", "execution_window_block", "mandate_expired"]
