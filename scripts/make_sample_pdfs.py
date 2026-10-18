"""Render the synthetic sample invoice as a PDF (needs reportlab)."""
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

src, out = "data/samples/invoice_northfield.txt", "data/samples/invoice_northfield.pdf"
c = canvas.Canvas(out, pagesize=A4)
y = 800
for line in open(src, encoding="utf-8").read().splitlines():
    c.drawString(50, y, line)
    y -= 18
c.save()
print("wrote", out)
