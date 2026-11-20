"""Generates demo media for the golden path: installer invoice PDF, boiler display photo, completion photo.
Run: python data/demo/make_assets.py  (needs reportlab + pillow)"""
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

OUT = Path(__file__).parent

def font(size):
    for name in ("arialbd.ttf", "DejaVuSans-Bold.ttf", "Arial Bold.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            pass
    return ImageFont.load_default()

def invoice():
    items = [("Anfahrtspauschale (Rahmenvertrag)", 1, 89.00),
             ("Arbeitszeit Heizungstechniker, Std.", 1, 72.00),
             ("Zündelektrode Vaillant ecoTEC plus (0020107800)", 1, 38.50)]
    net = sum(q * p for _, q, p in items); vat = round(net * 0.19, 2); gross = round(net + vat, 2)
    c = canvas.Canvas(str(OUT / "invoice_RE-2026-1187.pdf"), pagesize=A4)
    w, h = A4
    c.setFont("Helvetica-Bold", 18); c.drawString(50, h - 60, "Heizung Schmidt GmbH")
    c.setFont("Helvetica", 9); c.drawString(50, h - 75, "Heizung · Sanitär · Kundendienst  |  Beispielweg 3, 52064 Aachen  |  USt-IdNr. DE000000000")
    c.setFont("Helvetica", 10)
    y = h - 120
    for line in ["An: reltix Hausverwaltung (für Eigentümerin Maria Becker)", "Objekt: Musterstraße 12, 52062 Aachen – Zentralheizung",
                 "Auftrag: Fall case_0001, gemeldet von Lena Hoffmann (Whg. 4b)"]:
        c.drawString(50, y, line); y -= 14
    c.setFont("Helvetica-Bold", 14); c.drawString(50, y - 20, "Rechnung RE-2026-1187")
    c.setFont("Helvetica", 10); c.drawString(50, y - 36, "Rechnungsdatum: 21.11.2026   Leistungsdatum: 21.11.2026")
    y -= 70
    c.setFont("Helvetica-Bold", 10); c.drawString(50, y, "Leistung"); c.drawString(380, y, "Menge"); c.drawString(440, y, "Einzel"); c.drawString(500, y, "Gesamt")
    c.setFont("Helvetica", 10)
    for desc, q, p in items:
        y -= 18; c.drawString(50, y, desc); c.drawString(390, y, str(q)); c.drawRightString(480, y, f"{p:.2f} €"); c.drawRightString(545, y, f"{q*p:.2f} €")
    y -= 30
    for label, val in [("Netto", net), ("USt. 19 %", vat), ("Gesamt", gross)]:
        c.drawString(400, y, label); c.drawRightString(545, y, f"{val:.2f} €"); y -= 16
    c.setFont("Helvetica", 9)
    c.drawString(50, y - 20, "Befund: Störung F.28 (Zündung fehlgeschlagen). Zündelektrode verschlissen, ersetzt. Anlage geprüft, läuft.")
    c.drawString(50, y - 34, "Zahlbar innerhalb 14 Tagen. Vielen Dank für Ihren Auftrag.")
    c.save()
    return {"invoice_number": "RE-2026-1187", "net_eur": net, "vat_eur": vat, "gross_eur": gross}

def boiler_photo():
    img = Image.new("RGB", (1080, 1350), (232, 232, 228)); d = ImageDraw.Draw(img)
    d.rounded_rectangle([140, 200, 940, 1150], 40, fill=(245, 245, 242), outline=(180, 180, 175), width=6)
    d.text((200, 260), "Vaillant", font=font(70), fill=(30, 120, 60))
    d.text((200, 350), "ecoTEC plus", font=font(44), fill=(90, 90, 90))
    d.rounded_rectangle([260, 520, 820, 760], 20, fill=(20, 30, 25))
    d.text((330, 560), "F.28", font=font(150), fill=(120, 230, 140))
    for i, x in enumerate((300, 460, 620)):
        d.ellipse([x, 860, x + 110, 970], fill=(70, 70, 70))
    img.save(OUT / "boiler_display_F28.jpg", quality=88)

def done_photo():
    img = Image.new("RGB", (1080, 1350), (232, 232, 228)); d = ImageDraw.Draw(img)
    d.rounded_rectangle([140, 200, 940, 1150], 40, fill=(245, 245, 242), outline=(180, 180, 175), width=6)
    d.text((200, 260), "Vaillant", font=font(70), fill=(30, 120, 60))
    d.rounded_rectangle([260, 520, 820, 760], 20, fill=(20, 30, 25))
    d.text((320, 570), "55 °C", font=font(130), fill=(120, 230, 140))
    d.text((230, 1000), "Zündelektrode getauscht ✓", font=font(48), fill=(40, 40, 40))
    img.save(OUT / "repair_done.jpg", quality=88)

if __name__ == "__main__":
    print(invoice()); boiler_photo(); done_photo(); print("written to", OUT)
