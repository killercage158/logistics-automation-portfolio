# Trucking: haulier price files

The trucking team's guide for the road leg from the customer's pickup place to the
loading port. The AI reader follows it for each haulier's spreadsheet. The haulier files
have no common layout: route lists, matrices and pasted email text all occur.
(All hauliers, places and prices in this demo are fictional.)

## Your job

For every price in the file report: haulier, pickup place, port, truck type, price per
trip in VND, the diesel price per litre the quote is based on, and the validity date.

## Citation (required)

Two citations per price: the cell holding the **price** and the cell holding the
**diesel base price** (often a note at the top of the sheet). Code re-opens both.

## Rules

### TR-01 Read every haulier file, cite every cell
Read all the files in the folder, whatever their layout. Never calculate or fill gaps.
If you are not sure about a price, leave it out.

### TR-02 Every cited cell is verified
Code checks that the price cell holds the number you gave, that its row (or the top of
its column) names the pickup place, the port and the truck type, and that the diesel cell
holds the diesel price you gave. A failed check rejects the price, with the reason.

### TR-03 Fuel-indexed price
A trucking price is part fixed and part moves with the diesel price. In this demo the split
is 70% fixed and 30% fuel (an invented split):

`price today = quoted price x (0.70 + 0.30 x diesel today / diesel base in the quote)`

Only the freight price is adjusted, never fees. If no diesel price is known for the date,
the price is not adjusted and the option says so.

### TR-04 Validity
A quote past its validity date is dropped and listed with the reason.

### TR-05 Truck type follows the container
20GP uses a 20ft trailer. 40GP and 40HC use a 40ft trailer. One trip per container.

### TR-06 Keep the alternatives
Every verified haulier stays in the list with its adjusted price. The trucking team ranks
them; it does not choose for the customer.

### TR-07 Identical prices are doubtful
If two hauliers' files quote exactly the same price for the same leg, flag both ("possible
copied file, check it"). Never drop them.
