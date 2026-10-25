# Evidence-boundary UI

The chat already shows source excerpts and timestamp links in source cards. This
change adds an explicit notice for weaker evidence levels:

- `related`: a related teaching was found, but may not directly answer the exact question.
- `none`: the question was not clearly covered in indexed satsangs; general context
  should not be read as a direct statement from Premanand Ji.

The notice is deliberately categorical, not a probability score. The existing
retrieval thresholds are heuristics and are not calibrated confidence probabilities.
Continue to validate the wording in Hindi, Hinglish, and English during user testing.
