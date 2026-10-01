import pytest
from thursday_tool_server.domain.patching import PatchError, apply_unified_diff

ORIGINAL = "one\ntwo\nthree\nfour\nfive\n"


def test_simple_hunk() -> None:
    diff = "--- a/f\n+++ b/f\n@@ -2,3 +2,3 @@\n two\n-three\n+THREE\n four\n"
    assert apply_unified_diff(ORIGINAL, diff) == "one\ntwo\nTHREE\nfour\nfive\n"


def test_hunk_still_applies_when_the_file_shifted() -> None:
    shifted = "zero\nextra\n" + ORIGINAL
    diff = "@@ -2,3 +2,3 @@\n two\n-three\n+THREE\n four\n"
    assert apply_unified_diff(shifted, diff) == "zero\nextra\none\ntwo\nTHREE\nfour\nfive\n"


def test_two_hunks_with_line_count_changes() -> None:
    diff = "@@ -1,2 +1,3 @@\n one\n+one-and-a-half\n two\n@@ -4,2 +5,1 @@\n four\n-five\n"
    assert apply_unified_diff(ORIGINAL, diff) == "one\none-and-a-half\ntwo\nthree\nfour\n"


def test_crlf_and_missing_final_newline_are_kept() -> None:
    assert apply_unified_diff("a\r\nb\r\n", "@@ -1,2 +1,2 @@\n a\n-b\n+B\n") == "a\r\nB\r\n"
    assert apply_unified_diff("a\nb", "@@ -1,2 +1,2 @@\n a\n-b\n+B\n") == "a\nB"


def test_new_file_from_empty() -> None:
    assert apply_unified_diff("", "--- /dev/null\n+++ b/new\n@@ -0,0 +1,2 @@\n+x\n+y\n") == "x\ny\n"


def test_mismatch_is_an_error_not_a_guess() -> None:
    with pytest.raises(PatchError, match="hunk 1 does not match"):
        apply_unified_diff(ORIGINAL, "@@ -2,2 +2,2 @@\n two\n-THREE-not-there\n+x\n")


def test_not_a_diff() -> None:
    with pytest.raises(PatchError, match="no hunks"):
        apply_unified_diff(ORIGINAL, "just some text")
