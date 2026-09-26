from tfor.filters import MessageFields, evaluate_filters


def step(kind: str, field: str, mode: str, values: list[str], position: int) -> dict:
    return {
        "id": position + 1,
        "position": position,
        "kind": kind,
        "field": field,
        "match_mode": mode,
        "values": values,
        "enabled": True,
    }


def test_ordered_pipeline_short_circuits_on_sender_blacklist() -> None:
    steps = [
        step("blacklist", "sender_name", "contains", ["广告"], 0),
        step("whitelist", "text", "contains", ["发布"], 1),
    ]

    passed, results = evaluate_filters(
        steps,
        MessageFields(text="项目正式发布", sender_name="广告推广员", sender_username="staff", sender_id=42),
    )

    assert passed is False
    assert [result["outcome"] for result in results] == ["REJECT"]
    assert "广告" not in str(results)  # logs must not contain matched message/sender fragments


def test_whitelist_must_match_and_any_value_is_enough() -> None:
    whitelist = [step("whitelist", "text", "exact", ["alpha", "Beta"], 0)]

    assert evaluate_filters(whitelist, MessageFields(text="BETA"))[0] is True
    assert evaluate_filters(whitelist, MessageFields(text="Beta release"))[0] is False


def test_disabled_and_invalid_regex_steps_do_not_crash() -> None:
    steps = [
        {**step("blacklist", "text", "contains", ["blocked"], 0), "enabled": False},
        step("blacklist", "text", "regex", ["[invalid"], 1),
    ]

    passed, results = evaluate_filters(steps, MessageFields(text="blocked"))

    assert passed is True
    assert len(results) == 1
