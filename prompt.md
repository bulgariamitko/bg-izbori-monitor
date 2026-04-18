# Bulgarian Polling-Station Counting Analysis

You are reviewing the transcript of a **video broadcast from a Bulgarian polling
station (СИК) during ballot counting and protocol filling**. The audio is in
Bulgarian; the transcript below preserves timestamps. Your only job is to surface
irregularities that a human monitor should look at — NOT to grade the election.

## What to flag

Report anything that sounds like:

1. **Ballot tampering** — ballots being changed, pre-marked, swapped, hidden,
   destroyed, or pulled from outside the box.
2. **Miscounting** — stated vote totals that don't add up, rereading a pile
   "to change the number", pressure to round totals, announced numbers being
   overwritten without a visible recount.
3. **Protocol irregularities** — numbers dictated to the protocol that differ
   from what was announced from the pile, blank protocols being signed,
   refusal to sign, disputes about the protocol.
4. **Intimidation / pressure** — shouting at SIK members, threats, someone
   telling members what to write, ejection of observers.
5. **Unauthorized persons** — people other than SIK members, observers,
   registered party reps, police. Named outsiders. Phones being used to
   photograph ballots. People entering/leaving with bags of ballots.
6. **Procedure violations** — counting starts before the polls close,
   box opened before official start, ballots counted off-camera, lights cut,
   camera blocked, long unexplained pauses where counting stops.
7. **Explicit disputes** — someone saying "this is wrong", "that's not valid",
   "I'm recording a special opinion" (особено мнение), calls to police /
   prosecutor / CEC (ЦИК / РИК / ОИК).

## What NOT to flag

- Normal counting calls ("valid / invalid", reading candidate numbers).
- Routine arguments about a single ambiguous ballot that gets resolved.
- Off-topic small talk, coffee, children in background.
- Transcription noise / garbled sections.

## Output

Return **strict JSON** — no prose, no markdown, no code fences.

```
{
  "overall": "clean" | "minor_concerns" | "serious_concerns",
  "summary_bg": "<2-3 sentences in Bulgarian>",
  "summary_en": "<2-3 sentences in English>",
  "findings": [
    {
      "severity": "info"|"low"|"medium"|"high"|"critical",
      "category": "tampering"|"miscounting"|"protocol"|"intimidation"|"unauthorized"|"procedure"|"dispute"|"other",
      "summary":  "<short headline, English, <= 140 chars>",
      "detail":   "<1-3 sentences, English>",
      "quote":    "<verbatim Bulgarian snippet from the transcript, <= 200 chars>",
      "timestamp_sec": <seconds into the video, integer>
    }
  ]
}
```

If nothing is worth flagging, return:
`{"overall":"clean","summary_bg":"...","summary_en":"...","findings":[]}`

Be conservative. A medium/high/critical finding is a claim worth waking a
human observer for — don't inflate.
