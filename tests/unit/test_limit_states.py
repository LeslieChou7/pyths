"""开板与回封字段的合成离线样本。"""

from pathlib import Path

from pyths._limit_codec import decode_limit_pool

BASE = Path(__file__).resolve().parents[1] / "fixtures/synthetic"


def rows(name):
    return {
        row.code: row.fields
        for row in decode_limit_pool(
            (BASE / f"limit-state-{name}.json").read_bytes()
        ).rows
    }


def test_observed_open_and_reseal_values():
    before = rows("up-before")
    opened = rows("broken-after")
    resealed = rows("up-resealed")
    assert (before["900301"]["open_num"], before["900301"]["is_again_limit"]) == (1, 1)
    assert (opened["900301"]["open_num"], opened["900301"]["is_again_limit"]) == (2, 0)
    assert before["900302"]["open_num"] is None
    assert (opened["900302"]["open_num"], opened["900302"]["is_again_limit"]) == (1, 0)
    assert (resealed["900302"]["open_num"], resealed["900302"]["is_again_limit"]) == (
        1,
        1,
    )
    assert (
        rows("up-before-page2")["900303"]["open_num"],
        opened["900303"]["open_num"],
        resealed["900303"]["open_num"],
    ) == (1, 2, 2)


def test_transient_null_is_not_zero_and_times_remain_distinct():
    before = rows("up-before")["900303"]
    after = rows("up-null-counter")["900303"]
    assert before["open_num"] == 1 and after["open_num"] is None
    assert after["is_again_limit"] == 1
    assert before["first_limit_up_time"] == after["first_limit_up_time"] == "1760000050"
    assert before["last_limit_up_time"] == "1760000300"
    assert after["last_limit_up_time"] == "1760000999"
