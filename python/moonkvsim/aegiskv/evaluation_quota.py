"""Explicit fixed-quota comparator for a moving foreground safety ceiling.

The historical static_hbm variant retains a downward-clamped quota. This
experiment comparator reapplies its configured fixed target at each control
window, always bounded by the same current foreground/reserve ceiling. It is
separate from the frozen current runtime and its earlier experiment outputs.
"""

from __future__ import annotations

from .current.runtime import CurrentRuntime


class FixedQuotaRuntime(CurrentRuntime):
    def __init__(self, *args, fixed_quota_bytes: int, **kwargs):
        if type(fixed_quota_bytes) is not int or fixed_quota_bytes < 0:
            raise ValueError("fixed quota must be a nonnegative integer")
        if kwargs.get("policy", "static_hbm") != "static_hbm":
            raise ValueError("fixed-quota comparator requires static_hbm policy")
        kwargs["policy"] = "static_hbm"
        super().__init__(*args, **kwargs)
        if fixed_quota_bytes > self.config.hbm_cap_bytes:
            raise ValueError("fixed quota exceeds configured replica cap")
        self.fixed_quota_bytes = fixed_quota_bytes
        for adapter in self.adapters.values():
            adapter.quota = min(
                fixed_quota_bytes,
                self.config.hbm_bytes_per_rank - self.config.reserve_bytes,
            )

    def _apply_fixed_ceiling(self) -> None:
        c = self.config
        for worker in sorted(self.alive):
            for rank in range(c.tp):
                ledger = self.ledgers[f"hbm:{worker}:{rank}"]
                serving = sum(
                    size
                    for account, size in ledger.accounts.items()
                    if account.startswith("primary:")
                )
                ceiling = max(
                    0, min(c.hbm_cap_bytes, c.hbm_bytes_per_rank - serving - c.reserve_bytes)
                )
                adapter = self.adapters[worker, rank]
                old, adapter.quota = adapter.quota, min(self.fixed_quota_bytes, ceiling)
                if old != adapter.quota:
                    self._record(
                        "fixed_quota_ceiling",
                        worker=worker,
                        rank=rank,
                        before=old,
                        after=adapter.quota,
                        serving_bytes=serving,
                        configured_quota_bytes=self.fixed_quota_bytes,
                    )

    def _control(self) -> None:
        self._apply_fixed_ceiling()
        super()._control()

    def run(self) -> dict:
        result = super().run()
        result["quota_comparator"] = {
            "kind": "fixed-target-with-live-safety-ceiling",
            "configured_quota_bytes": self.fixed_quota_bytes,
            "regrowth": "reapply target at next control window after foreground releases",
            "admission_reclaim_and_reader_leases": "unchanged current runtime",
        }
        return result
