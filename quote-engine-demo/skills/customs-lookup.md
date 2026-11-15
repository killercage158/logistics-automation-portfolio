# Customs lookup

The customs team's guide for one product: which HS code, which duty and VAT, whether a
licence or an inspection applies, and what clearance costs. The AI proposes; code decides.
(All HS codes, rates, fees and legal documents in this demo are fictional.)

## Your job

Given a product, return candidate HS codes (best first). For each: the 8-digit code, a short
description, the legal basis (document name and **one sentence copied word for word** from
that document) and `doubt` (empty if you are sure, otherwise say why not).

Do **not** state duty rates, VAT rates, licence or inspection requirements. The code takes
those from the tariff table.

## Citation (required)

The legal document name and the exact sentence. Code searches the document for that
sentence.

## Rules

### CU-01 The HS code must exist
Code looks the code up in the tariff table. A code that is not there is rejected, however
plausible it sounds.

### CU-02 The legal quote must be in the document
The quoted sentence must appear in the cited document (case, accents and spacing are
ignored). If it does not, the legal basis is shown as "not verified" and is not shown as a
citation.

### CU-03 Rates and flags come from the table
Duty %, VAT % and the licence / inspection flags are copied by code from the tariff row of
the HS code and the direction (import or export). The AI never supplies them.

### CU-04 Duty and VAT
`duty = duty rate x customs value`, and `VAT = VAT rate x (customs value + duty)`. VAT is
charged on the value plus the duty.

### CU-05 Licence and inspection
A licence requirement adds the licence processing fee and a procedure note. Physical or
document inspection adds the matching handling fee and a note. The broker's declaration fee
always applies.

### CU-06 Doubt is a visible warning
Show a warning when: several plausible codes exist, you stated a doubt, the legal basis could
not be verified, or no AI answer is available (then staff can type the HS code by hand and
the same checks run on it).
