# 原始转写校正规则

## Immutable Source

`transcription.text` and the prerequisite transcript file are immutable evidence. Copy the raw text into the downstream run directory, but never modify the ingest artifact.

## Allowed Corrections

- Traditional-to-Simplified conversion.
- Punctuation and paragraph restoration.
- Obvious homophone repair supported by surrounding clauses, title, and segment timing.
- Removal of repeated fragments clearly caused by ASR decoding.
- Repair of missing common particles when the spoken meaning is otherwise unambiguous.
- Normalization of common Douyin relationship-content vocabulary such as `断联`, `复联`, `新欢`, `挽回`, `情绪价值`, and `心心念念` only when context supports it.

## Forbidden Corrections

- Adding a sentence because it would make the script more persuasive.
- Replacing an unclear claim with a likely internet phrase.
- Changing the speaker's conclusion or advice.
- Silently deleting a passage whose meaning is uncertain.
- Calling the corrected result the official or exact original text.

## Uncertainty Markers

Use:

- `〔听不清〕` when no reliable candidate exists.
- `〔疑似：断联〕` when one candidate is likely but not certain.
- A correction note when a material phrase was inferred from context.

## Quality Grades

### usable

The core meaning and sentence sequence are clear. Corrections are limited to punctuation and a few obvious words.

### needs_correction

The meaning is recoverable, but repeated homophones, malformed segmentation, or mixed Simplified/Traditional output require substantive editing. Every material correction must be listed.

### unreliable

The opening, central claim, or several consecutive clauses are incoherent. Correct only context-supported content, mark unresolved passages, and avoid unsupported claims in the rewrite. Do not automatically request or download a stronger ASR model. A stronger transcription may be requested only when the user explicitly asks for it or explicitly approves a retry.

## ASR Retry Policy

- The default action after receiving a transcript is AI contextual correction.
- Many wrong words, repeated homophones, or several malformed clauses do not by themselves justify retranscription.
- Never automatically download or invoke `small`, `medium`, `large`, or another ASR model.
- If the central meaning cannot be recovered, keep uncertainty markers and report the limitation.
- Retry ASR only after explicit user instruction or approval.

## Clean Transcript Shape

- Use natural Chinese punctuation.
- Start a new paragraph when the speaker changes rhetorical function.
- Preserve spoken particles only when they contribute to tone.
- Do not over-polish the text into formal written prose.
