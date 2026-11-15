# Dispatch: from a new lead to work for the departments

How a lead becomes work items, deadlines and reminders. The code simulates it on a clock
that starts when the lead arrives. (All times in this demo are fictional.)

## Rules

### DP-01 One work item per department the lead needs
Sea freight is always needed, so Booking always gets an item. Trucking gets one when the lead
has a pickup place. Customs gets one when the lead names a product. A department that is
not needed gets no item.

### DP-02 Every item has a deadline
The deadline is 30 minutes after the item is created.

### DP-03 Reminders while an item is open
While an item is not answered, reminders go out at fixed times after creation (40, 60 and 90
minutes in this demo). The first goes to the person who has the item; later ones also go to
the department leader.

### DP-04 Accept or decline
A department can accept an item or decline it with a reason. A decline goes back to Sales
Support, who can type a manual answer or ask another way.

### DP-05 A manual entry is an answer
An item is answered when the department has delivered options from the system or typed a
price by hand. Both finish the item.

### DP-06 Everyone answered
When every item is answered, Sales Support is told that there are enough options and can
pick and set the margin.

### DP-07 One item per department per lead
Dispatching the same lead twice does not create a second item for a department.
