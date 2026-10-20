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


def test_text_matching_ignores_zero_width_characters() -> None:
    for field in ("text", "sender_name", "sender_username"):
        for mode in ("contains", "exact", "regex"):
            for char in ("\u200b", "\u200c", "\u200d", "\u2060", "\ufeff"):
                value = r"外省\s*[:：]\s*[是可🉑]" if mode == "regex" else "外省：可"
                for kind in ("blacklist", "whitelist"):
                    filters = [step(kind, field, mode, [value], 0)]
                    original = f"{char}外{char}省{char}：{char}可{char}"
                    fields = MessageFields(**{field: original})
                    assert evaluate_filters(filters, fields)[0] is (kind == "whitelist")
                    assert getattr(fields, field) == original
                    assert evaluate_filters(filters, MessageFields(**{field: "外省：否"}))[0] is (
                        kind == "blacklist"
                    )


def test_regex_blacklist_with_zero_width_characters_in_multiline_body() -> None:
    filters = [step("blacklist", "text", "regex", [r"外省\s*[:：]\s*[是可🉑]"], 0)]
    for text in (
        "有没有纹身：无\n能否飞外省\u200b：可以\n能否出村：安全国家",
        "可否其他城市：可\n可否飞往外省：\ufeff可\n最快多久出发:15号",
    ):
        assert evaluate_filters(filters, MessageFields(text=text))[0] is False

    # Preserve real whitespace and regex syntax rather than flattening all text.
    exact = [step("whitelist", "text", "exact", ["ab"], 0)]
    for text in ("a b", "a\nb", "a\tb"):
        assert evaluate_filters(exact, MessageFields(text=text))[0] is False
    escaped = [step("whitelist", "text", "regex", [r"a\sb"], 0)]
    assert evaluate_filters(escaped, MessageFields(text="a\u200b b"))[0] is True
