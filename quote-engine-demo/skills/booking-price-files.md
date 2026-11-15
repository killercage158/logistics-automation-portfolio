# Booking: ocean freight prices

This is the booking team's guide. The AI reader follows it when it reads a carrier's
price spreadsheet, and the code that checks the AI's answer enforces the same rules.
(All carriers, prices and numbers in this demo are fictional.)

## Your job

You receive the cells of one price workbook, one cell per line (`C5 | 2150`). List every
ocean freight price written in it. You never calculate, convert or guess a price.

## Citation (required for every price)

Give the sheet name and the exact cell where the **price number** sits. Code will
re-open that cell. If the number is not there, or the row does not name the two ports,
your price is rejected and shown to the team with the reason.

## Rules

### BK-01 Price check only, never booking
We look up prices. Nothing in this system books, reserves or confirms space. A carrier
may show a price for a lane it will not book; the number is still a valid reference.

### BK-02 Contract first
If the lane has a valid contract rate for a carrier, that rate is the price and the
carrier's website is not checked. An expired contract is ignored and the carrier is
checked normally.

### BK-03 Live portal price first; price files fill gaps
Order of trust for one carrier: contract, then a manual entry, then the live portal
price, then a price read from a spreadsheet. A lower-trust price is shown as
"superseded", never deleted.

### BK-04 Expired prices are dropped
A price whose validity date is before the pricing date is not used. It is listed, with the
reason, so the team can see what was left out. Always report the validity date when the
file shows one, as `YYYY-MM-DD`; use `null` only when the file has no date at all.

### BK-05 Doubtful data is flagged, never dropped
Report everything the file contains. If something looks odd (no validity date, validity
ending within a week, a price far below the other options, a price that comes from a
spreadsheet rather than a live check) the system adds a warning next to it. Staff
decide. Do not exclude a row because you doubt it.

### BK-06 Cargo type
Charcoal and general cargo are priced separately. Report the cargo type if the file says
which one the price is for (`general`, `charcoal`), otherwise `null`. A price for the
other cargo is not used. Some carriers do not accept charcoal at all: that answer is final.
Charcoal options carry a handling reminder (dangerous-goods declaration and packing may
be required); the team confirms it with the carrier.

### BK-07 Manual entry
Staff can always type a price by hand. It joins the same ranking, is labelled "manual"
and applies only to the request it was typed for. It is not saved for later requests.

### BK-08 Portal outcomes
A temporary failure (site down, login problem, timeout) is retried later, in a new
smaller run containing only the carriers that failed. A "no price for this lane" or
"cargo not accepted" answer is final and is never retried. A carrier that still fails
after the last retry is reported as "gave up".

### BK-09 Every AI-read price is verified
Code opens the cell you cited, compares the number (written forms such as `USD 3,450`
and `1.250,00` are understood) and checks that the row names both ports. Wrong or
invented prices are rejected and shown with the reason.
