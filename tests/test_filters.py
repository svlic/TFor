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
            for char in (
                "\u200b", "\u200c", "\u200d", "\u2060", "\ufeff",
                "\u00ad", "\u034f", "\u061c", "\u115f", "\u1160",
                "\u17b4", "\u17b5", "\u180b", "\u180e", "\u180f",
                "\u200e", "\u200f", "\u202a", "\u202e", "\u2064",
                "\u2066", "\u2069", "\u206f", "\u3164", "\ufe0e",
                "\ufe0f", "\uffa0", "\ufff0", "\ufff8", "\U0001bca0",
                "\U0001bca3", "\U0001d173", "\U0001d17a", "\U000e0001",
                "\U000e0061", "\U000e007f", "\U000e0100", "\U000e01ef",
                "\x00", "\x08", "\x1b", "\x7f", "\x80",
            ):
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


def test_unicode_compatibility_and_composition_for_matching() -> None:
    for mode in ("contains", "exact", "regex"):
        for original, value in (
            ("ＡｂＣ：１２", "abc:12"),
            ("𝐀𝒃𝘊", "abc"),
            ("oﬃce", "office"),
            ("cafe\u034f\u0301", "café"),
            ("外省：🉑️", "外省:可"),
            ("a\u00a0b\u3000c", "a b c"),
        ):
            filters = [step("whitelist", "text", mode, [value], 0)]
            fields = MessageFields(text=original)
            assert evaluate_filters(filters, fields)[0] is True
            assert fields.text == original

    # Literal values use the same normalization without mutating saved rules.
    for mode in ("contains", "exact"):
        filters = [step("whitelist", "text", mode, ["Ａ\u2066Ｂ\ufe0f"], 0)]
        assert evaluate_filters(filters, MessageFields(text="ab"))[0] is True
        assert filters[0]["values"] == ["Ａ\u2066Ｂ\ufe0f"]
        assert evaluate_filters(filters, MessageFields(text="ac"))[0] is False


def test_normalization_preserves_meaningful_distinctions_and_regex_syntax() -> None:
    for text, value in (
        ("café", "cafe"),
        ("а", "a"),  # Cyrillic is not Latin.
        ("a b", "ab"),
        ("a\nb", "ab"),
        ("a\tb", "ab"),
        ("a\u00a0b", "ab"),
        ("क", "क\u093f"),  # A vowel sign is not an ignorable mark.
    ):
        for mode in ("contains", "exact", "regex"):
            filters = [step("whitelist", "text", mode, [f"^{value}$" if mode == "regex" else value], 0)]
            assert evaluate_filters(filters, MessageFields(text=text))[0] is False

    # Normalizing a fullwidth regex metacharacter would change its syntax.
    filters = [step("whitelist", "text", "regex", ["a．b"], 0)]
    assert evaluate_filters(filters, MessageFields(text="axb"))[0] is False
    filters = [step("whitelist", "text", "regex", [r"^a\.b\s\d+$"], 0)]
    assert evaluate_filters(filters, MessageFields(text="ａ．ｂ\u00a0１２"))[0] is True
    assert evaluate_filters(filters, MessageFields(text="axb 12"))[0] is False


def test_invisible_only_literals_do_not_match_every_message() -> None:
    for mode in ("contains", "exact"):
        for kind in ("blacklist", "whitelist"):
            filters = [step(kind, "text", mode, ["\u200b\u3164\ufe0f"], 0)]
            for text in ("ordinary message", "", "\u200b"):
                assert evaluate_filters(filters, MessageFields(text=text))[0] is (kind == "blacklist")
