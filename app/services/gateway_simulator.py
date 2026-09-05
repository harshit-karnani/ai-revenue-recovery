import asyncio
import random
import datetime
from typing import Dict, Any, Optional
from app.core.regulatory_rules import (
    IST_TZ,
    EXECUTION_BLOCK_START,
    EXECUTION_BLOCK_END,
    AFTERNOON_VALID_START,
    AFTERNOON_VALID_END,
    NIGHT_VALID_START
)
from app.services.regulatory_engine import get_next_valid_execution_window

class GatewaySimulator:
    """
    Simulates gateway execution side effects deterministically based on seed, strategy, bucket, and timing.
    """
    def __init__(self, seed: Optional[int] = 42):
        self.rng = random.Random(seed)

    def calculate_rescheduled_time(self, current_time: datetime.datetime) -> datetime.datetime:
        """
        Computes the next valid execution time outside both blocked windows.
        """
        return get_next_valid_execution_window(current_time)

    async def execute_strategy(
        self,
        strategy_name: str,
        payload: Optional[Dict[str, Any]] = None,
        bucket: Optional[str] = "B",
        current_time: Optional[datetime.datetime] = None
    ) -> str:
        """
        Executes a strategy against the mock gateway.
        Returns: 'executed', 'failed', or 'pending'
        """
        await asyncio.sleep(0.01)
        payload = payload or {}
        
        if payload.get("force_gateway_failure", False):
            return "failed"
        if payload.get("force_gateway_success", False):
            return "executed"

        # 1. trigger_reauthentication_link -> user action simulation
        if strategy_name == "trigger_reauthentication_link":
            p = self.rng.random()
            if p < 0.70:
                return "executed"
            elif p < 0.90:
                return "pending"
            return "failed"

        # 2. reschedule_valid_window -> high success if landed in valid window
        if strategy_name == "reschedule_valid_window":
            return "executed" if self.rng.random() < 0.90 else "failed"

        # 3. switch_gateway / switch_network -> great for processing_error / timeout
        if strategy_name in ("switch_gateway", "switch_network", "backup_gateway"):
            return "executed" if self.rng.random() < 0.85 else "failed"

        # 4. delay_retry / short_delay_retry -> varies by bucket and timing
        if strategy_name in ("delay_retry", "short_delay_retry"):
            if current_time and payload.get("payment_type") == "upi_autopay":
                local_time = current_time.astimezone(IST_TZ).time()
                is_blocked = (EXECUTION_BLOCK_START <= local_time < EXECUTION_BLOCK_END) or \
                             (AFTERNOON_VALID_END <= local_time < NIGHT_VALID_START)
                if is_blocked:
                    return "failed"

            if bucket == "A":
                success_prob = 0.75 if strategy_name == "delay_retry" else 0.40
            else:
                success_prob = 0.85 if strategy_name == "short_delay_retry" else 0.70

            return "executed" if self.rng.random() < success_prob else "failed"

        # Default fallback
        return "executed" if self.rng.random() < 0.80 else "failed"
