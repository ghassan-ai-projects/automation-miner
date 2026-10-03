# SOP MC-07 — Motor Claims First Notice of Loss (FNOL) Intake

> **Synthetic example.** Nordlicht Versicherung AG is a fictional mid-sized German
> motor and household insurer. All names, systems, and figures are invented for
> evaluating automation-miner and do not describe any real organization.

Owner: Head of Claims Operations (Hamburg) · Version 4.2 · Last reviewed March 2026

## 1. Scope

Applies to all motor claims (Kfz-Haftpflicht, Teilkasko, Vollkasko) reported by
policyholders, brokers, or third parties. Household and liability claims follow SOP HC-03.

## 2. Channels and volumes

| Channel | Share of FNOL | Notes |
|---|---:|---|
| Phone (claims hotline, 7:00–20:00) | 46% | Agent types notes into ClaimsDesk free-text field |
| Email to schaden@ (PDF / photos attached) | 31% | Shared Outlook mailbox, 6 intake clerks |
| Broker portal upload | 15% | Structured form, but 40% of uploads attach a scanned paper form instead |
| Paper mail (Schadenanzeige form) | 8% | Scanned by the Bochum mailroom, arrives as TIFF in DocuWare |

Average volume: **1,850 motor FNOLs per week**, peaking at ~3,400 in the week after a hail
storm or the first frost week. The intake team is 14 FTE (6 email/paper clerks, 8 hotline agents).

## 3. Intake procedure

1. **Identify the policy.** Search the policy number in PolisPro (policy admin, AS/400).
   If no policy number is given (≈22% of email FNOLs), search by licence plate, then by
   name + postcode. Average lookup time when the number is missing: 6 minutes.
2. **Check cover.** Confirm the policy was active on the loss date and the coverage type
   matches the claim (e.g. glass damage requires Teilkasko). Premium arrears are checked
   in the separate collections screen in PolisPro.
3. **Create the claim** in ClaimsDesk (claims system, vendor product, REST API available
   since the 2025 upgrade but only used by the broker portal). Re-key: loss date, location,
   vehicle, other party, police report number, description. Average keying time: 9 minutes
   per claim for email/paper, 4 minutes for broker portal.
4. **Attach documents** from Outlook or DocuWare into ClaimsDesk manually (drag and drop).
5. **Classify complexity**: `simple` (glass, parking damage < €2,500, no injury),
   `standard`, or `complex` (injury, total loss, suspected fraud, foreign vehicle).
   Classification is by clerk judgement using the checklist in Annex B.
6. **Route**: simple claims go to the Fast Track team; standard to regional handlers by
   postcode; complex to Senior Handling. Fraud indicators (Annex C, 17 red flags) must be
   ticked manually and, if ≥ 3 apply, the claim is copied to the SIU (special investigations)
   mailbox.
7. **Acknowledge** to the customer within 1 working day using Word template ACK-04,
   personalised by hand and sent from the shared mailbox.

## 4. Service levels and controls

- Acknowledgement within 1 working day (BaFin complaint statistics are reviewed quarterly).
- Claim created within 2 working days of receipt. Current achievement: 71% (target 95%).
- 4-eyes check on 10% random sample of created claims by the team lead. The Q1 2026 sample
  found field errors in 8.5% of claims (wrong loss date or coverage type most common).
- GDPR: health data for injury claims must only be visible to Senior Handling.

## 5. Known issues (from the Q1 2026 operations review)

- After storm events the email backlog reaches 2,500+ unread messages; acknowledgements
  slip to 4–6 days and complaint volume doubles.
- Duplicate claims: the same loss is reported by policyholder, broker, and the other
  party's insurer; ~6% of created claims are later merged as duplicates.
- Misrouting: ~12% of `standard` claims are re-routed by the regional handler because
  the postcode or complexity class was wrong, adding on average 2.5 days of cycle time.
- Fraud red-flag ticking is inconsistent between clerks; SIU estimates that only ~35% of
  claims that later proved fraudulent had been flagged at intake.
