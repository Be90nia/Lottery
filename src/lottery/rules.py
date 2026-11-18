"""Versioned Super Lotto prize rules; unsupported historical eras fail closed."""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any


class UnsupportedRulesetError(ValueError):
    """Raised when no sufficiently evidenced ruleset covers a draw."""


@dataclass(frozen=True)
class PrizeTier:
    tier: int
    match_patterns: tuple[tuple[int, int], ...]
    fixed_prize_below_threshold_yuan: Decimal | None
    fixed_prize_at_or_above_threshold_yuan: Decimal | None
    floating: bool = False
    additional_multiplier: Decimal | None = Decimal("0")


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
    floating_award_notes: str
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
            return tier.fixed_prize_at_or_above_threshold_yuan
        return tier.fixed_prize_below_threshold_yuan

    def additional_award_multiplier(self, tier_number: int) -> Decimal | None:
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
            "floating_award_notes": self.floating_award_notes,
            "tiers": [
                {
                    "tier": tier.tier,
                    "match_patterns": [list(pattern) for pattern in tier.match_patterns],
                    "fixed_prize_below_threshold_yuan": (
                        str(tier.fixed_prize_below_threshold_yuan)
                        if tier.fixed_prize_below_threshold_yuan is not None else None
                    ),
                    "fixed_prize_at_or_above_threshold_yuan": (
                        str(tier.fixed_prize_at_or_above_threshold_yuan)
                        if tier.fixed_prize_at_or_above_threshold_yuan is not None else None
                    ),
                    "floating": tier.floating,
                    "additional_multiplier": (
                        str(tier.additional_multiplier)
                        if tier.additional_multiplier is not None else None
                    ),
                }
                for tier in self.tiers
            ],
            "source_urls": list(self.source_urls),
        }


_RULES_2009_APPROVAL = "https://zhs.mof.gov.cn/zhengcefabu/201811/t20181122_3073538.htm"
_RULES_2009_EFFECTIVE = "https://www.js-lottery.com/cms/post-2935.html"
_RULES_2013_APPROVAL = "https://zhs.mof.gov.cn/zhengcefabu/201312/t20131219_1026921.htm"
_RULES_2013_EFFECTIVE = "https://sports.sina.com.cn/l/2026-01-30/doc-inhkacxm7033487.shtml"
_RULES_2014_SOURCE = "https://www.mof.gov.cn/tzgg/201404/t20140421_1069584.htm"
_RULES_2014_EFFECTIVE_NOTICE = "https://yntc8.cn/news/2014042229140.html"
_RULES_2019_SOURCE = "https://www.nmtc.com.cn/gyzl/17631.html"
_RULES_2019_EFFECTIVE_SOURCE = "https://society.yunnan.cn/system/2019/02/28/030214030.shtml"
_RULES_2026_PDF = "https://static.sporttery.cn/res_1_0/cmsv2/upload/docfile/202601/1511220935li.pdf"
_RULES_2026_ANNOUNCEMENT = "https://www.sporttery.cn/digitallottery/cjdlt/20260205/10052315.html"

_EIGHT_TIER_PATTERNS = (
    ((5, 2),),
    ((5, 1),),
    ((5, 0),),
    ((4, 2),),
    ((4, 1),),
    ((4, 0), (3, 2)),
    ((3, 1), (2, 2)),
    ((3, 0), (1, 2), (2, 1), (0, 2)),
)


def _eight_tier_schedule() -> tuple[PrizeTier, ...]:
    return (
        PrizeTier(1, _EIGHT_TIER_PATTERNS[0], None, None, True, Decimal("0.6")),
        PrizeTier(2, _EIGHT_TIER_PATTERNS[1], None, None, True, Decimal("0.6")),
        PrizeTier(3, _EIGHT_TIER_PATTERNS[2], None, None, True, Decimal("0.6")),
        PrizeTier(4, _EIGHT_TIER_PATTERNS[3], Decimal("3000"), Decimal("3000"), False, Decimal("0.5")),
        PrizeTier(5, _EIGHT_TIER_PATTERNS[4], Decimal("600"), Decimal("600"), False, Decimal("0.5")),
        PrizeTier(6, _EIGHT_TIER_PATTERNS[5], Decimal("100"), Decimal("100"), False, Decimal("0.5")),
        PrizeTier(7, _EIGHT_TIER_PATTERNS[6], Decimal("10"), Decimal("10"), False, Decimal("0.5")),
        PrizeTier(8, _EIGHT_TIER_PATTERNS[7], Decimal("5"), Decimal("5")),
    )


RULES_2007 = PrizeRuleset(
    ruleset_id="dlt_2007_from_07001",
    effective_from_draw_id="07001",
    effective_through_draw_id="09120",
    effective_from_date="2007-05-30",
    jackpot_threshold_yuan=None,
    floating_per_ticket_cap_yuan=Decimal("5000000"),
    floating_total_cap_per_tier_yuan=None,
    floating_award_notes=(
        "Tiers 1-3 are floating (70%/25%/5% of the amount remaining after "
        "fixed awards). Additional betting participates only in floating tiers "
        "and pays 60% of the corresponding basic-bet floating award. "
        "This module does not calculate floating awards."
    ),
    source_urls=(
        "https://news.sohu.com/20070501/n249819058.shtml",
        "https://www.js-lottery.com/cms/post-2573.html",
    ),
    tiers=(
        PrizeTier(1, _EIGHT_TIER_PATTERNS[0], None, None, True, Decimal("0.6")),
        PrizeTier(2, _EIGHT_TIER_PATTERNS[1], None, None, True, Decimal("0.6")),
        PrizeTier(3, _EIGHT_TIER_PATTERNS[2], None, None, True, Decimal("0.6")),
        PrizeTier(4, _EIGHT_TIER_PATTERNS[3], Decimal("3000"), Decimal("3000")),
        PrizeTier(5, _EIGHT_TIER_PATTERNS[4], Decimal("500"), Decimal("500")),
        PrizeTier(6, _EIGHT_TIER_PATTERNS[5], Decimal("200"), Decimal("200")),
        PrizeTier(7, _EIGHT_TIER_PATTERNS[6], Decimal("10"), Decimal("10")),
        PrizeTier(8, _EIGHT_TIER_PATTERNS[7], Decimal("5"), Decimal("5")),
    ),
)

RULES_2009 = PrizeRuleset(
    ruleset_id="dlt_2009_from_09121",
    effective_from_draw_id="09121",
    effective_through_draw_id="13144",
    effective_from_date="2009-10-14",
    jackpot_threshold_yuan=None,
    floating_per_ticket_cap_yuan=Decimal("5000000"),
    floating_total_cap_per_tier_yuan=None,
    floating_award_notes=(
        "Tiers 1-3 are floating (75%/20%/5% of the amount remaining after "
        "fixed awards); additional betting pays 60% on floating tiers and "
        "50% on fixed tiers 4-7. This module does not calculate floating awards."
    ),
    source_urls=(_RULES_2009_APPROVAL, _RULES_2009_EFFECTIVE),
    tiers=_eight_tier_schedule(),
)

RULES_2013 = PrizeRuleset(
    ruleset_id="dlt_2013_from_13145",
    effective_from_draw_id="13145",
    effective_through_draw_id="14051",
    effective_from_date="2013-12-09",
    jackpot_threshold_yuan=None,
    floating_per_ticket_cap_yuan=Decimal("5000000"),
    floating_total_cap_per_tier_yuan=None,
    floating_award_notes=(
        "The 2013 change primarily altered funding proportions to 51% prize, "
        "14% issue expense, and 35% public welfare (with 49% current prize "
        "and 2% adjustment fund). The eight-tier prize schedule and 60%/50% "
        "additional multipliers remain as in the 2009 schedule."
    ),
    source_urls=(_RULES_2013_APPROVAL, _RULES_2013_EFFECTIVE),
    tiers=_eight_tier_schedule(),
)

RULES_2014 = PrizeRuleset(
    ruleset_id="dlt_2014_from_14052",
    effective_from_draw_id="14052",
    effective_through_draw_id="19018",
    effective_from_date="2014-05-05",
    jackpot_threshold_yuan=None,
    floating_per_ticket_cap_yuan=Decimal("5000000"),
    floating_total_cap_per_tier_yuan=None,
    floating_award_notes=(
        "Tiers 1-3 are floating. The 2014 rules describe tier-1 pool allocation "
        "bands below ¥100m, ¥100m-¥300m, and at/above ¥300m; tiers 2 and 3 "
        "receive 18% and 7% of the amount remaining after fixed awards. "
        "This module does not calculate those floating awards."
    ),
    source_urls=(_RULES_2014_SOURCE, _RULES_2014_EFFECTIVE_NOTICE),
    tiers=(
        PrizeTier(1, ((5, 2),), None, None, True, Decimal("0.6")),
        PrizeTier(2, ((5, 1),), None, None, True, Decimal("0.6")),
        PrizeTier(3, ((5, 0), (4, 2)), None, None, True, Decimal("0.6")),
        PrizeTier(4, ((4, 1), (3, 2)), Decimal("200"), Decimal("200"), False, Decimal("0.5")),
        PrizeTier(5, ((4, 0), (3, 1), (2, 2)), Decimal("10"), Decimal("10"), False, Decimal("0.5")),
        PrizeTier(6, ((3, 0), (1, 2), (2, 1), (0, 2)), Decimal("5"), Decimal("5")),
    ),
)

RULES_2019 = PrizeRuleset(
    ruleset_id="dlt_2019_from_19019",
    effective_from_draw_id="19019",
    effective_through_draw_id="26013",
    effective_from_date="2019-02-20",
    jackpot_threshold_yuan=None,
    floating_per_ticket_cap_yuan=Decimal("5000000"),
    floating_total_cap_per_tier_yuan=None,
    floating_award_notes=(
        "Tiers 1-2 are floating. The 2019 rules allocate 78%/22% of the amount "
        "remaining after fixed awards to tiers 1/2, subject to tier-1 jackpot "
        "bands and per-ticket caps. This module does not calculate floating awards."
    ),
    source_urls=(_RULES_2019_SOURCE, _RULES_2019_EFFECTIVE_SOURCE),
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
    floating_award_notes=(
        "Tiers 1-2 are floating. The 2026 rules add a ¥100m single-draw total "
        "cap per floating tier and use a tier-1 pool schedule. This module does "
        "not calculate floating awards."
    ),
    source_urls=(_RULES_2026_PDF, _RULES_2026_ANNOUNCEMENT),
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
    numeric_id = int(draw_id)
    if numeric_id >= 26014:
        return RULES_2026
    if numeric_id >= 19019:
        return RULES_2019
    if numeric_id >= 14052:
        return RULES_2014
    if numeric_id >= 13145:
        return RULES_2013
    if numeric_id >= 9121:
        return RULES_2009
    if numeric_id >= 7001:
        return RULES_2007
    raise UnsupportedRulesetError(
        f"draw {draw_id} predates the first Super Lotto draw 07001"
    )
