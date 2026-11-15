"""Create ALL the fake input data for the demo in data/sample/.

Everything is invented: carriers, prices, dates, contract numbers.

  price_files/   three messy carrier spreadsheets with three different layouts
                 (merged headers, notes rows, prices in different columns, prices
                 stored as text such as "USD 650", a sheet of pasted email text,
                 and one price that has already expired)
  contracts.csv                 negotiated rates (one of them is expired)
  local_charges_general.csv     standard origin charges (THC, DOC, SEAL, TLX, AMS)
  local_charges_carrier.csv     carrier-specific (and carrier + cargo) charges: these WIN over the general table
  freetime.csv                  free days at POL / POD from the carrier guides, with port / cargo exceptions
  manual_prices_example.csv     example of a price typed by staff (use with --manual)
  trucking/                     three messy haulier files (route list, matrix, pasted email text)
  diesel_price.csv              diesel price per litre by date (for the fuel-indexed trucking price)
  manual_trucking_example.csv   example of a trucking price typed by staff (use with --manual-trucking)
  customs/                      a fake tariff table, a fake fee table and two fake legal documents

The dates are fixed (not "today") so the recorded AI answers in fixtures/ always match.
Run:  python data/make_sample_data.py
"""
import csv
import datetime as dt
from pathlib import Path

from openpyxl import Workbook

OUT = Path(__file__).parent / "sample"


def bluewave():
    """Layout 1: one row per lane, one column per container, merged title, notes rows."""
    wb = Workbook()
    ws = wb.active
    ws.title = "Spot Rates"
    ws["A1"] = "BLUEWAVE LINES - SPOT RATES FOR NOVEMBER 2026"
    ws.merge_cells("A1:F1")
    ws["A2"] = "Rates in USD per container. General cargo only. Subject to GRI and surcharges."
    ws.append([])
    ws.append(["POL", "POD", "20GP", "40GP", "40HC", "Valid until"])                      # row 4
    ws.append(["Hai Phong", "Los Angeles", 2150, 3300, 3450, dt.date(2026, 12, 15)])       # row 5
    ws.append(["Ho Chi Minh", "Rotterdam", 2900, 4650, 4800, dt.date(2026, 12, 15)])       # row 6
    ws.append(["Hai Phong", "Singapore", 410, 590, 620, dt.date(2026, 11, 10)])            # row 7: EXPIRED
    ws.append(["Ho Chi Minh", "Busan", 520, 880, 930, dt.date(2026, 12, 15)])              # row 8
    ws["A10"] = "Note: origin THC not included."
    return wb


def northstar():
    """Layout 2: two-level merged header, prices stored as TEXT, a second sheet of terms."""
    wb = Workbook()
    ws = wb.active
    ws.title = "Tariff"
    ws["A1"] = "NORTHSTAR SHIPPING - TARIFF"
    ws["A2"] = "All rates are for general cargo. USD per container."
    ws["A3"], ws["B3"], ws["C3"], ws["F3"] = "Port of loading", "Port of discharge", "Ocean freight USD", "Validity"
    for rng in ("A3:A4", "B3:B4", "C3:E3", "F3:F4"):
        ws.merge_cells(rng)
    ws["C4"], ws["D4"], ws["E4"] = "20'", "40'", "40'HC"
    ws.append(["Hai Phong", "Singapore", "USD 420", "USD 600", "USD 650", "31/12/2026"])   # row 5
    ws.append(["Ho Chi Minh", "Busan", 540, 900, 960, "31/12/2026"])                        # row 6
    ws.append(["Da Nang", "Busan", "USD 560", "USD 880", "USD 930", "31/12/2026"])          # row 7
    terms = wb.create_sheet("Terms")
    terms["A1"] = "Free time at destination: 7 days"
    terms["A2"] = "Bookings must be made 5 days before ETD"
    return wb


def pacific_arrow():
    """Layout 3: 'long' list (one row per lane AND container) + a sheet of pasted email text."""
    wb = Workbook()
    ws = wb.active
    ws.title = "Rate list"
    ws.append(["Route", "Equipment", "Cargo", "All-in rate (USD)", "Valid to"])          # row 1
    ws.append(["Hai Phong > Los Angeles", "20GP", "General", "2,250", "2026-12-15"])     # row 2
    ws.append(["Hai Phong > Los Angeles", "40HC", "General", "3,580", "2026-12-15"])     # row 3
    ws.append(["Ho Chi Minh > Busan", "40HC", "General", 1010, "2026-12-15"])            # row 4
    ws.append(["Ho Chi Minh > Busan", "40HC", "Charcoal", 1090, "2026-12-15"])           # row 5
    ws.append(["Ho Chi Minh > Busan", "20GP", "Charcoal", 610, "2026-12-15"])            # row 6
    ws.append(["Hai Phong > Singapore", "40HC", "General", "USD 655", "2026-12-15"])     # row 7
    ws.append(["Hai Phong > Busan", "40HC", "Charcoal", 1010, "2026-12-15"])             # row 8
    mail = wb.create_sheet("Email paste")      # text pasted from an email or PDF
    mail["A1"] = "Copied from carrier email:"
    mail["A2"] = "Ho Chi Minh to Rotterdam, 40HC, USD 4,720 all-in, valid until 31 Dec 2026"
    mail["A3"] = "Ho Chi Minh to Rotterdam, 20GP, USD 2,850 all-in, valid until 31 Dec 2026"
    mail["A4"] = "Rates are not guaranteed during peak season."
    return wb


def alpha_transport():
    """Trucking layout 1: a route list. Prices are numbers; the diesel base is in a note cell."""
    wb = Workbook()
    ws = wb.active
    ws.title = "Rates"
    ws["A1"] = "ALPHA TRANSPORT - TRUCKING RATES"
    ws["A2"] = "Prices in VND per trip, VAT excluded. Based on a diesel price of 20,000 VND per litre."
    ws.append([])
    ws.append(["From", "To", "20ft", "40ft", "Valid until"])                                   # row 4
    ws.append(["Bac Ninh", "Hai Phong", 3200000, 4100000, dt.date(2026, 12, 31)])               # row 5
    ws.append(["Ha Noi", "Hai Phong", 3000000, 3900000, dt.date(2026, 12, 31)])                 # row 6
    ws.append(["Hai Duong", "Hai Phong", 2400000, 3100000, dt.date(2026, 10, 31)])              # row 7: EXPIRED
    return wb


def beta_transport():
    """Trucking layout 2: a matrix. Pickup places down the side, port + truck across the top;
    prices are text in Vietnamese format (dots as thousands marks)."""
    wb = Workbook()
    ws = wb.active
    ws.title = "Rate card"
    ws["A1"] = "BETA TRANSPORT RATE CARD (VND per trip)"
    ws["A2"] = "Diesel base: 21,000 VND per litre"
    ws.append([])
    ws.append(["Pickup place", "Hai Phong 20ft", "Hai Phong 40ft", "Ho Chi Minh 40ft"])        # row 4
    ws.append(["Bac Ninh", "3.050.000", "4.100.000", "9.800.000"])                              # row 5
    ws.append(["Ha Noi", "2.900.000", "3.850.000", "9.600.000"])                                # row 6
    ws.append(["Hai Duong", "2.350.000", "3.050.000", "10.000.000"])                            # row 7
    ws["A9"] = "Valid until 31/12/2026"
    return wb


def gamma_haulage():
    """Trucking layout 3: text pasted from an email."""
    wb = Workbook()
    ws = wb.active
    ws.title = "Quote"
    ws["A1"] = "Pasted from email - Gamma Haulage:"
    ws["A2"] = "Bac Ninh to Hai Phong, 40ft trailer, VND 3,950,000, diesel base 20,500 VND/litre, valid until 10 Nov 2026"
    ws["A3"] = "Ha Noi to Hai Phong, 40ft trailer, VND 4,050,000, diesel base 20,500 VND/litre, valid until 31 Dec 2026"
    return wb


def make_trucking():
    (OUT / "trucking").mkdir(exist_ok=True)
    for name, wb in {"alpha_transport.xlsx": alpha_transport(), "beta_transport.xlsx": beta_transport(),
                     "gamma_haulage.xlsx": gamma_haulage()}.items():
        wb.save(OUT / "trucking" / name)
    write_csv("diesel_price.csv", ["date", "price_vnd"], [
        ["2026-10-01", 20500], ["2026-11-02", 21400], ["2026-11-14", 22000]])
    write_csv("manual_trucking_example.csv", ["haulier", "pickup", "port", "truck", "price_vnd", "valid_until", "note"], [
        ["Delta Logistics", "Bac Ninh", "Hai Phong", "40ft", 4050000, "2026-12-10", "phone quote, same day"],
        ["Epsilon Express", "Bac Ninh", "Hai Phong", "40ft", 4300000, "2026-12-10", "phone quote, same day"]])


DECREE = """FICTIONAL DECREE 12/2026 ON THE EXPORT OF FOREST PRODUCTS (invented for this demo)
Article 1. This decree applies to forest products leaving the country by sea.
Article 2. Bamboo charcoal is declared under subheading 4402.10.
Article 3. Wood charcoal for export shall be declared under heading 4402 and requires an export permit issued before customs clearance.
Article 5. Consignments of wood charcoal are subject to physical inspection at the port.
"""
CIRCULAR = """FICTIONAL CIRCULAR 08/2026 ON BUILDING MATERIALS (invented for this demo)
Article 1. This circular applies to building materials entering the country.
Article 2. Glazed ceramic floor tiles imported for construction are subject to document inspection.
"""


def make_customs():
    folder = OUT / "customs"
    (folder / "legal").mkdir(parents=True, exist_ok=True)
    (folder / "legal" / "fictional_decree_12_2026.txt").write_text(DECREE, encoding="utf-8")
    (folder / "legal" / "fictional_circular_08_2026.txt").write_text(CIRCULAR, encoding="utf-8")
    header = ["hs_code", "description", "import_duty_pct", "export_duty_pct", "import_vat_pct",
              "export_vat_pct", "licence_required", "inspection"]
    rows = [["44029000", "Wood charcoal, other than bamboo", 10, 5, 8, 0, "yes", "physical"],
            ["44021000", "Bamboo charcoal", 10, 0, 8, 0, "no", "documents"],
            ["69072100", "Glazed ceramic floor tiles", 12, 0, 8, 0, "no", "documents"],
            ["09011110", "Coffee, not roasted, not decaffeinated", 5, 0, 8, 0, "no", "none"]]
    for name, hdr, data in (("tariff.csv", header, rows), ("customs_fees.csv", ["item", "amount_vnd", "applies_when"], [
            ["Customs declaration (broker fee)", 1200000, "declaration"],
            ["Licence processing", 1500000, "licence"],
            ["Physical inspection handling", 800000, "inspection_physical"],
            ["Document inspection handling", 300000, "inspection_documents"]])):
        with open(folder / name, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(hdr)
            w.writerows(data)


def write_csv(name, header, rows):
    with open(OUT / name, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(rows)


def main():
    (OUT / "price_files").mkdir(parents=True, exist_ok=True)
    for name, wb in {"bluewave_spot_nov.xlsx": bluewave(), "northstar_tariff.xlsx": northstar(),
                     "pacific_arrow_quote.xlsx": pacific_arrow()}.items():
        wb.save(OUT / "price_files" / name)

    write_csv("contracts.csv",
              ["carrier", "pol", "pod", "container", "cargo", "price_usd", "valid_until", "contract_ref"], [
        ["Jade Ocean", "Hai Phong", "Singapore", "40HC", "general", 590, "2026-12-31", "C-JO-001"],
        ["Kestrel Line", "Ho Chi Minh", "Busan", "40HC", "charcoal", 1000, "2027-01-31", "C-KL-002"],
        ["Kestrel Line", "Hai Phong", "Busan", "40HC", "charcoal", 950, "2027-01-31", "C-KL-005"],
        ["Redsea Express", "Ho Chi Minh", "Busan", "40HC", "charcoal", 940, "2026-09-30", "C-RE-003"],  # expired
        ["Bluewave Lines", "Hai Phong", "Los Angeles", "40HC", "general", 3400, "2026-12-31", "C-BW-004"],
    ])
    write_csv("local_charges_general.csv", ["charge", "container", "amount_usd", "applies_to", "unit"], [
        ["THC", "20GP", 110, "all", ""], ["THC", "40GP", 165, "all", ""], ["THC", "40HC", 165, "all", ""],
        ["DOC", "any", 45, "all", ""], ["SEAL", "any", 10, "all", ""], ["TLX", "any", 25, "all", ""],
        ["AMS", "any", 35, "us_eu", ""],
    ])
    write_csv("local_charges_carrier.csv", ["carrier", "charge", "container", "amount_usd", "cargo", "unit"], [
        ["Kestrel Line", "THC", "20GP", 130, "", ""], ["Kestrel Line", "THC", "40GP", 195, "", ""],
        ["Kestrel Line", "THC", "40HC", 195, "", ""],
        ["Kestrel Line", "THC", "20GP", 150, "charcoal", ""], ["Kestrel Line", "THC", "40GP", 230, "charcoal", ""],
        ["Kestrel Line", "THC", "40HC", 230, "charcoal", ""],
    ])
    guide = lambda c: f"{c} D&D guide (fake)"
    ft = []
    for carrier, pol, pod in [("Bluewave Lines", 7, 10), ("Northstar Shipping", 5, 7), ("Pacific Arrow", 7, 7),
                              ("Jade Ocean", 10, 14), ("Kestrel Line", 5, 10)]:      # Redsea Express is missing on purpose
        ft += [[carrier, "POL", "", "", pol, guide(carrier)], [carrier, "POD", "", "", pod, guide(carrier)]]
    ft += [["Bluewave Lines", "POD", "Singapore", "", 12, guide("Bluewave Lines")],        # port exception
           ["Pacific Arrow", "POD", "Busan", "", 14, guide("Pacific Arrow")],               # port exception
           ["Kestrel Line", "POD", "Busan", "charcoal", 5, guide("Kestrel Line")]]          # port + cargo exception
    write_csv("freetime.csv", ["carrier", "place", "port", "cargo", "free_days", "guide"], ft)
    write_csv("manual_prices_example.csv",
              ["carrier", "pol", "pod", "container", "price_usd", "valid_until", "note"], [
        ["Redsea Express", "Hai Phong", "Singapore", "40HC", 570, "2026-12-10", "phone quote from carrier rep"],
        ["Pacific Arrow", "Ho Chi Minh", "Busan", "40HC", 1070, "2026-12-10", "email from sales rep"],
    ])
    make_trucking()
    make_customs()
    print("wrote sample data to", OUT)


if __name__ == "__main__":
    main()
