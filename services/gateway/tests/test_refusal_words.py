from thursday_gateway.transport.admin_api import refusal_words


def test_a_list_of_field_errors_reads_as_field_and_what_is_wrong() -> None:
    detail = [
        {
            "type": "string_pattern_mismatch",
            "loc": ["body", "base_url"],
            "msg": "String should match pattern '^https?://'",
            "input": "",
            "ctx": {"pattern": "^https?://"},
        },
        {"type": "greater_than_equal", "loc": ["body", "load", "context_length"], "msg": "Input should be >= 512"},
    ]
    assert refusal_words(detail) == (
        "base_url: String should match pattern '^https?://'; load.context_length: Input should be >= 512"
    )


def test_a_plain_reason_is_kept_as_it_is() -> None:
    assert refusal_words("No model is chosen for this agent.") == "No model is chosen for this agent."
    assert refusal_words("") == ""


def test_odd_entries_do_not_break_it_and_the_words_stay_short() -> None:
    assert refusal_words(["first", {"msg": "second"}, {"loc": ["body"]}, {}]) == "first; second"
    assert len(refusal_words([{"loc": ["body", "x"], "msg": "y" * 2000}])) == 500
