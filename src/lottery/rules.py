"""Versioned Super Lotto prize rules; floating awards are intentionally not calculated."""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any


@dataclass(frozen=True)
class PrizeTier:
    tier: int
    match_patterns: tuple[tuple[int, int], ...]
    fixed_below_threshold_yuan: Decimal | None
    fixed_at_or_above_threshold_yuan: Decimal | None
    floating: bool = False
    additional_multiplier: Decimal = Decimal("0")


@dataclass(frozen=True)
class PrizeRuleset:
    ruleset_id: str
    effective_from_draw_id: str | None
    effective_through_draw_id: str | None
    effective_from_date: str | None
    tiers: tuple[PrizeTier, ...]
    jackpot_threshold_yuan: Decimal | None
    floating_per_ticket_cap_yuan: Decimal | None
    floating_total_cap_per_tier_yuan: Decimal | None
    source_urls: tuple[str, ...]

    def tier_for_hits(self, front_hits: int, back_hits: int) -> int | None:
        if type(front_hits) is not int or not 0 <= front_hits <= 5:
            raise ValueError("front_hits must be an integer in 0..5")
        if type(back_hits) is not int or not 0 <= back_hits <= 2:
            raise ValueError("back_hits must be an integer in 0..2")
        for tier in self.tiers:
            if (front_hits, back_hits) in tier.match_patterns:
                return tier.tier
        return None

    def fixed_prize_yuan(self, tier_number: int, jackpot_yuan: Decimal | str | int) -> Decimal | None:
        tier = next((item for item in self.tiers if item.tier == tier_number), None)
        if tier is None:
            raise ValueError(f"unknown prize tier {tier_number} for {self.ruleset_id}")
        if tier.floating:
            return None
        try:
            jackpot = Decimal(str(jackpot_yuan))
        except (InvalidOperation, TypeError, ValueError) as exc:
            raise ValueError("jackpot_yuan must be a valid decimal amount") from exc
        if not jackpot.is_finite() or jackpot < 0:
            raise ValueError("jackpot_yuan must be finite and nonnegative")
        if self.jackpot_threshold_yuan is not None and jackpot >= self.jackpot_threshold_yuan:
            return tier.fixed_at_or_above_threshold_yuan
        return tier.fixed_below_threshold_yuan

    def additional_award_multiplier(self, tier_number: int) -> Decimal:
        tier = next((item for item in self.tiers if item.tier == tier_number), None)
        if tier is None:
            raise ValueError(f"unknown prize tier {tier_number} for {self.ruleset_id}")
        return tier.additional_multiplier

    def as_dict(self) -> dict[str, Any]:
        return {
            "ruleset_id": self.ruleset_id,
            "effective_from_draw_id": self.effective_from_draw_id,
            "effective_through_draw_id": self.effective_through_draw_id,
            "effective_from_date": self.effective_from_date,
            "jackpot_threshold_yuan": (
                str(self.jackpot_threshold_yuan) if self.jackpot_threshold_yuan is not None else None
            ),
            "floating_per_ticket_cap_yuan": (
                str(self.floating_per_ticket_cap_yuan)
                if self.floating_per_ticket_cap_yuan is not None else None
            ),
            "floating_total_cap_per_tier_yuan": (
                str(self.floating_total_cap_per_tier_yuan)
                if self.floating_total_cap_per_tier_yuan is not None else None
            ),
            "tiers": [
                {
                    "tier": tier.tier,
                    "match_patterns": [list(pattern) for pattern in tier.match_patterns],
                    "fixed_below_threshold_yuan": (
                        str(tier.fixed_below_threshold_yuan)
                        if tier.fixed_below_threshold_yuan is not None else None
                    ),
                    "fixed_at_or_above_threshold_yuan": (
                        str(tier.fixed_at_or_above_threshold_yuan)
                        if tier.fixed_at_or_above_threshold_yuan is not None else None
                    ),
                    "floating": tier.floating,
                    "additional_multiplier": str(tier.additional_multiplier),
                }
                for tier in self.tiers
            ],
            "source_urls": list(self.source_urls),
        }


_LEGACY_SOURCE = "https://m.sporttery.cn/bzzx/20210207/3002858.html?gid=5"
_NEW_RULES_PDF = "https://static.sporttery.cn/res_1_0/cmsv2/upload/docfile/202601/1511220935li.pdf"
_NEW_RULE_ANNOUNCEMENT = "https://www.sporttery.cn/digitallottery/cjdlt/20260205/10052315.html"

LEGACY_RULES = PrizeRuleset(
    ruleset_id="dlt_pre_26014",
    effective_from_draw_id=None,
    effective_through_draw_id="26013",
    effective_from_date=None,
    jackpot_threshold_yuan=None,
    floating_per_ticket_cap_yuan=Decimal("5000000"),
    floating_total_cap_per_tier_yuan=None,
    source_urls=(_LEGACY_SOURCE,),
    tiers=(
        PrizeTier(1, ((5, 2),), None, None, True, Decimal("0.8")),
        PrizeTier(2, ((5, 1),), None, None, True, Decimal("0.8")),
        PrizeTier(3, ((5, 0),), Decimal("10000"), Decimal("10000")),
        PrizeTier(4, ((4, 2),), Decimal("3000"), Decimal("3000")),
        PrizeTier(5, ((4, 1),), Decimal("300"), Decimal("300")),
        PrizeTier(6, ((3, 2),), Decimal("200"), Decimal("200")),
        PrizeTier(7, ((4, 0),), Decimal("100"), Decimal("100")),
        PrizeTier(8, ((3, 1), (2, 2)), Decimal("15"), Decimal("15")),
        PrizeTier(9, ((3, 0), (1, 2), (2, 1), (0, 2)), Decimal("5"), Decimal("5")),
    ),
)

RULES_2026 = PrizeRuleset(
    ruleset_id="dlt_2026_from_26014",
    effective_from_draw_id="26014",
    effective_through_draw_id=None,
    effective_from_date="2026-02-02",
    jackpot_threshold_yuan=Decimal("800000000"),
    floating_per_ticket_cap_yuan=Decimal("5000000"),
    floating_total_cap_per_tier_yuan=Decimal("100000000"),
    source_urls=(_NEW_RULES_PDF, _NEW_RULE_ANNOUNCEMENT),
    tiers=(
        PrizeTier(1, ((5, 2),), None, None, True, Decimal("0.8")),
        PrizeTier(2, ((5, 1),), None, None, True, Decimal("0.8")),
        PrizeTier(3, ((5, 0), (4, 2)), Decimal("5000"), Decimal("6666")),
        PrizeTier(4, ((4, 1),), Decimal("300"), Decimal("380")),
        PrizeTier(5, ((4, 0), (3, 2)), Decimal("150"), Decimal("200")),
        PrizeTier(6, ((3, 1), (2, 2)), Decimal("15"), Decimal("18")),
        PrizeTier(7, ((3, 0), (2, 1), (1, 2), (0, 2)), Decimal("5"), Decimal("7")),
    ),
)


def ruleset_for_draw(draw_id: str) -> PrizeRuleset:
    if not isinstance(draw_id, str) or len(draw_id) != 5 or not draw_id.isdigit():
        raise ValueError("draw_id must be a five-digit numeric string")
    if int(draw_id) >= int(RULES_2026.effective_from_draw_id or "26014"):
        return RULES_2026
    return LEGACY_RULES
