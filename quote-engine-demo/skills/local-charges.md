# Local charges at the origin port

The booking team's guide for the fees paid at the loading port on top of the ocean
freight. Code applies these rules to the fee tables. In production an AI reader follows
the same guide when it reads the team's fee workbooks and cites every cell.
(All amounts in this demo are fictional.)

## Citation (required for every fee)

The table (file and sheet) and the cell holding the amount, and the cell that names the
fee. Code re-opens both.

## Rules

### LC-01 Charge sources form a cascade
Take each charge from the most specific table that has it:
1. a table for this carrier **and** this cargo type,
2. a table for this carrier,
3. the general table.

A later source only **fills** charges the earlier ones lack. No table is thrown away; it
simply ranks lower. The report says which table each fee came from.

### LC-02 Required export fee set
Every option must carry these origin fees: **THC, DOC, SEAL, TLX**. For destinations in
the USA or Europe, **AMS** (advance manifest) is required as well. If a required fee is in
no table, the option is flagged "total is incomplete". The fee is never silently counted
as zero.

### LC-03 Per container or per bill of lading
THC and SEAL are charged per container. DOC, TLX and AMS are charged once per bill of
lading, however many containers there are. If the table states a unit, use the table's
unit. Total for N containers = (per-container charges x N) + (per-B/L charges once).

### LC-04 Included fees are not added twice
If the carrier's own quote says a fee is included in its price, the table fee is not
added. The fee stays visible in the option with an amount of zero and the reason.
