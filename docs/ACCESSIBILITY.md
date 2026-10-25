# Accessibility and multilingual QA checklist

Run this pass on mobile and desktop, with keyboard-only navigation and at least
one screen reader (VoiceOver on macOS/iOS is a useful first pass).

- [ ] Language selector is announced as “Answer language” and all options can be
  selected by keyboard.
- [ ] New assistant messages use a language tag for Hindi, Latin-script Hinglish,
  or English so assistive technology can choose an appropriate pronunciation.
- [ ] Source cards announce the video title and timestamp, and are keyboard
  reachable with a visible focus outline.
- [ ] Chat status changes (searching, errors, completion) are announced politely
  without repeatedly reading the entire conversation.
- [ ] Evidence badges, excerpts, and timestamps remain understandable without
  relying on color alone.
- [ ] Test mixed Devanagari/Latin text, enlarged text, dark mode, and narrow screens.
- [ ] Check focus order and focus return after auth, feedback, and delete dialogs.

This checklist records intended checks; it is not a claim that a full screen-reader
audit has already passed.
