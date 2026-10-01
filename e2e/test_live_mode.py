"""Live interview mode, end to end in Chromium with a fake microphone.

AC-09: the whole flow in CI (start -> transcript -> question detected ->
suggestion -> summary). AC-10: the session summary and "Copy summary".
AC-08 (UI half): with Deepgram down, the notice shows and text mode works.
AC-13 (UI half): Nova-3's real mid-sentence cut of Q2 ends in ONE card with
the full question. AC-12 (browser half): the page only talks to the app.
"""

from urllib.parse import urlsplit

from conftest import ORIGIN

Q1 = "Tell me about a project you're proud of."
Q2 = "Can you walk me through how you would design a rate limiter for a public API?"


def start_listening(page) -> None:
    page.goto(f"{ORIGIN}/interview")
    page.get_by_role("button", name="Microphone").click()
    page.get_by_role("button", name="Start listening").click()


def test_live_session_from_audio_to_summary(page, stack):
    start_listening(page)
    page.get_by_role("status").filter(has_text="Listening").wait_for(timeout=15_000)

    # The first question is detected and answered without a click.
    page.locator("mark", has_text=Q1).wait_for(timeout=20_000)
    page.get_by_text(f"Suggested answer to: {Q1}").wait_for(timeout=10_000)

    # Q2 is cut after "Can you walk me through" and continued: one card, full text.
    page.locator("mark", has_text=Q2).wait_for(timeout=30_000)
    page.get_by_text(f"Suggested answer to: {Q2}").wait_for(timeout=10_000)
    assert page.locator("mark").count() == 1
    transcript = page.get_by_role("list", name="Transcript").locator("li").all_inner_texts()
    assert transcript == [Q1, Q2]

    page.get_by_role("button", name="This helped").click()
    page.get_by_role("button", name="Stop listening").click()
    page.get_by_role("status").filter(has_text="Not listening").wait_for(timeout=10_000)

    summary = page.get_by_role("region", name="Session summary")
    summary.wait_for(timeout=5_000)
    text = summary.inner_text()
    assert "2 (2 detected automatically, 0 with Suggest now)" in text
    assert "1 of 1 rated" in text
    assert "p50" in text and "p90" in text

    page.get_by_role("button", name="Copy summary").click()
    page.get_by_text("Copied.").wait_for(timeout=3_000)
    copied = page.evaluate("navigator.clipboard.readText()")
    assert copied.startswith("CareerAI interview session, ")
    assert "Questions: 2 (2 detected automatically, 0 with Suggest now)" in copied
    assert "Useful: 1 of 1 rated" in copied
    assert "Platform (Meet, Zoom web, Teams web, other):" in copied

    assert stack.close_streams >= 1  # Stop let the provider flush and close
    hosts = {urlsplit(url).netloc for url in page.requests}
    assert hosts == {"127.0.0.1:8123"}, hosts  # never Deepgram or any other host


def test_with_deepgram_down_the_text_mode_still_answers(page, stack):
    stack.down = True
    try:
        start_listening(page)
        alert = page.get_by_role("alert").filter(has_text="Live transcription isn't available right now")
        alert.wait_for(timeout=15_000)
        alert.get_by_role("button", name="Type a question").click()
        page.get_by_role("textbox").fill("How would you design a rate limiter?")
        page.get_by_role("button", name="Get Suggestion").click()
        page.get_by_text("Suggested answer to: How would you design a rate limiter?").wait_for(timeout=10_000)
    finally:
        stack.down = False
