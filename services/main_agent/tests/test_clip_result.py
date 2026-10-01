from thursday_main_agent.application.tasks import CLIPPED_NOTE, clip_result


def test_short_results_are_untouched() -> None:
    assert clip_result("Done. Three files.") == "Done. Three files."


def test_long_results_end_at_a_sentence_and_say_they_were_shortened() -> None:
    text = "First paragraph. " * 30 + "\n\n" + "Second paragraph with **bold** text. " * 400
    clipped = clip_result(text, limit=1000)
    assert len(clipped) <= 1000 and clipped.endswith(CLIPPED_NOTE)
    body = clipped[: -len(CLIPPED_NOTE)]
    assert body.endswith(".") and body.count("**") % 2 == 0, "never cut inside a word or a bold marker"
