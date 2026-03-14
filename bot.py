import logging
import sqlite3
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes
from fpdf import FPDF
from datetime import date
import re
import os
import json

# Variables seguras
TOKEN = os.getenv('BOT_TOKEN')
if not TOKEN:
    print("❌ BOT_TOKEN requerido!")
    exit(1)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def get_db():
    conn = sqlite3.connect('boletas.db')
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS boletas
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  datum TEXT, kunde TEXT, ort TEXT, leistung TEXT, 
                  preis TEXT, pdf_datei TEXT, status TEXT)''')
    conn.commit()
    return conn, c

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🎉 Boletapp LIVE!\n\n"
        "📄 /rechnung \"Kunde\" Ort \"Leistung\" Preis\n"
        "📋 /liste\n"
        "🗑️ /delete ID\n"
        "💾 /export CSV"
    )

async def rechnung(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = ' '.join(context.args).strip()
    if not args:
        await update.message.reply_text('/rechnung "Max Mustermann" Berlin "Corte Hombre" 25EUR')
        return
    
    match = re.match(r'"([^"]+)"\s+([^"]+)\s+"([^"]+)"\s+(.+)', args)
    if not match:
        await update.message.reply_text('❌ Formato: /rechnung "Kunde" Ort "Leistung" 25EUR')
        return
    
    kunde, ort, leistung, preis = match.groups()
    
    pdf_path = generiere_pdf(kunde, ort, leistung, preis)
    
    # SQLite
    conn, c = get_db()
    heute = date.today().strftime("%d.%m.%Y")
    c.execute("INSERT INTO boletas (datum, kunde, ort, leistung, preis, pdf_datei, status) VALUES (?, ?, ?, ?, ?, ?, ?)",
              (heute, kunde, ort, leistung, preis.replace('€', 'EUR'), pdf_path, "Aktiv"))
    boleta_id = c.lastrowid
    conn.commit()
    conn.close()
    
    await update.message.reply_text(
        f"✅ Rechnung {boleta_id} erstellt!\n"
        f"👤 {kunde}\n"
        f"📍 {ort}\n"
        f"💇 {leistung}\n"
        f"💰 {preis}"
    )
    
    with open(pdf_path, 'rb') as f:
        await update.message.reply_document(f, filename=f"Rechnung-{boleta_id}.pdf")

async def liste(update: Update, context: ContextTypes.DEFAULT_TYPE):
    conn, c = get_db()
    c.execute("SELECT id, kunde, leistung, preis FROM boletas WHERE status='Aktiv' ORDER BY id DESC LIMIT 10")
    rows = c.fetchall()
    conn.close()
    
    if not rows:
        await update.message.reply_text("Keine boletas.")
        return
    
    text = "📋 Letzte boletas:\n\n"
    for row in rows:
        text += f"ID {row[0]}: {row[1]} - {row[2]} ({row[3]})\n"
    await update.message.reply_text(text)

async def delete(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("/delete <ID>")
        return
    try:
        boleta_id = int(context.args[0])
        conn, c = get_db()
        c.execute("UPDATE boletas SET status='Gelöscht' WHERE id=?", (boleta_id,))
        conn.commit()
        conn.close()
        await update.message.reply_text(f"✅ ID {boleta_id} gelöscht.")
    except:
        await update.message.reply_text("❌ Ungültige ID.")

async def export(update: Update, context: ContextTypes.DEFAULT_TYPE):
    conn, c = get_db()
    c.execute("SELECT * FROM boletas")
    rows = c.fetchall()
    conn.close()
    
    import io
    import csv
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["ID", "Datum", "Kunde", "Ort", "Leistung", "Preis", "PDF", "Status"])
    writer.writerows(rows)
    
    buf = io.BytesIO(output.getvalue().encode())
    buf.name = "boletas.csv"
    await update.message.reply_document(buf)

def generiere_pdf(kunde, ort, leistung, preis):
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Arial", 12)
    
    heute = date.today().strftime("%d.%m.%Y")
    
    pdf.cell(200, 10, "RECHNUNG §19 UStG", 0, 1, "C")
    pdf.cell(200, 10, f"Datum: {heute}", 0, 1)
    pdf.ln(10)
    
    pdf.cell(100, 10, "Von:", 0, 1)
    pdf.cell(100, 10, "DEIN NAME", 0, 1)
    pdf.cell(100, 10, "DEINE ADRESSE", 0, 1)
    
    pdf.ln(5)
    pdf.cell(100, 10, "An:", 0, 1)
    pdf.cell(100, 10, kunde, 0, 1)
    pdf.cell(100, 10, ort, 0, 1)
    
    pdf.ln(10)
    pdf.cell(80, 10, "Leistung:", 0, 1)
    pdf.cell(120, 10, leistung, 0, 1)
    pdf.cell(80, 10, "Preis:", 0, 1)
    pdf.cell(120, 10, preis.replace('€', 'EUR'), 0, 1)
    
    pdf.cell(200, 10, "Keine USt gem. §19 UStG", 0, 1, "C")
    
    pdf_path = f"rechnung_{kunde.replace(' ', '_')}.pdf"
    pdf.output(pdf_path)
    return pdf_path

def main():
    app = Application.builder().token(TOKEN).build()
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("rechnung
