import logging
import sqlite3
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes
from fpdf import FPDF
from datetime import date
import csv
import io
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import re
import os
import json

TOKEN = os.getenv('BOT_TOKEN')

# Variables de entorno
SCOPE = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
GOOGLE_CREDS = json.loads(os.getenv('GOOGLE_CREDS', '{}'))

if GOOGLE_CREDS:
    with open('temp_creds.json', 'w') as f:
        json.dump(GOOGLE_CREDS, f)
    CREDS_FILE = 'temp_creds.json'

def get_db():
    conn = sqlite3.connect('boletas.db')
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS boletas
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  datum TEXT, kunde TEXT, ort TEXT, leistung TEXT, 
                  preis TEXT, pdf_datei TEXT, status TEXT)''')
    conn.commit()
    return conn, c

def connect_sheets():
    creds = ServiceAccountCredentials.from_json_keyfile_name(CREDS_FILE, SCOPE)
    client = gspread.authorize(creds)
    return client.open("Boletapp Rechnungen").sheet1

logging.basicConfig(level=logging.INFO)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Hallo! Kommandos:\n"
        "/rechnung \"Max Mustermann\" Berlin \"Corte Hombre\" 25EUR"
        "/liste → Letzte 10\n"
        "/delete ID → Lösche\n"
        "/export → CSV"
    )

async def rechnung(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = ' '.join(context.args).strip()
    
    if not args:
        await update.message.reply_text('Verwendung: /rechnung "Kunde" Ort "Leistung" Preis')
        return
    
    match = re.match(r'"([^"]+)"\s+([^"]+)\s+"([^"]+)"\s+(.+)', args)
    if not match:
        await update.message.reply_text('❌ Format: /rechnung "Max Mustermann" Berlin "Corte Hombre" 25€')
        return
    
    kunde, ort, leistung, preis = match.groups()
    
    # Genera PDF
    pdf_path = generiere_pdf(kunde, ort, leistung, preis)
    
    # Guarda SQLite
    conn, c = get_db()
    heute = date.today().strftime("%d.%m.%Y")
    c.execute("INSERT INTO boletas (datum, kunde, ort, leistung, preis, pdf_datei, status) VALUES (?, ?, ?, ?, ?, ?, ?)",
              (heute, kunde, ort, leistung, preis, pdf_path, "Aktiv"))
    sqlite_id = c.lastrowid
    conn.commit()
    conn.close()
    
    # Guarda Sheets
    try:
        sheet = connect_sheets()
        sheet_id = len(sheet.get_all_values())
        sheet.append_row([sqlite_id, heute, kunde, ort, leistung, preis, pdf_path, "Aktiv"])
        await update.message.reply_text(
            f"✅ Rechnung {sqlite_id} erstellt!\n"
            f"SQLite ID: {sqlite_id}\n"
            f"Sheets ID: {sheet_id}\n"
            f"Kunde: {kunde}"
        )
    except Exception as e:
        await update.message.reply_text(f"✅ SQLite OK, Sheets Fehler: {str(e)}")
    
    # Envía PDF
    with open(pdf_path, 'rb') as f:
        await update.message.reply_document(f, filename=f"Rechnung-{sqlite_id}.pdf")

# [Mantén las funciones liste, delete, export, generiere_pdf y main igual que antes]

async def liste(update: Update, context: ContextTypes.DEFAULT_TYPE):
    conn, c = get_db()
    c.execute("SELECT id, kunde, leistung, preis FROM boletas WHERE status='Aktiv' ORDER BY id DESC LIMIT 10")
    rows = c.fetchall()
    conn.close()
    
    if not rows:
        await update.message.reply_text("Keine boletas.")
        return
    
    text = "Letzte boletas:\n\n"
    for row in rows:
        text += f"ID {row[0]}: {row[1]} - {row[2]} ({row[3]})\n"
    await update.message.reply_text(text)

async def delete(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Verwendung: /delete <ID>")
        return
    
    boleta_id = int(context.args[0])
    conn, c = get_db()
    c.execute("UPDATE boletas SET status='Gelöscht' WHERE id=?", (boleta_id,))
    if c.rowcount > 0:
        await update.message.reply_text(f"✅ Boleta {boleta_id} gelöscht (SQLite).")
    conn.commit()
    conn.close()

async def export(update: Update, context: ContextTypes.DEFAULT_TYPE):
    conn, c = get_db()
    c.execute("SELECT * FROM boletas")
    rows = c.fetchall()
    conn.close()
    
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["ID", "Datum", "Kunde", "Ort", "Leistung", "Preis", "PDF", "Status"])
    writer.writerows(rows)
    
    buf = io.BytesIO(output.getvalue().encode())
    buf.name = "boletas.csv"
    await update.message.reply_document(buf, filename="boletas.csv")

def generiere_pdf(kunde, ort, leistung, preis):
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Arial", size=12)
    
    heute = date.today().strftime("%d.%m.%Y")
    
    pdf.cell(200, 10, txt="RECHNUNG (Kleinunternehmer §19 UStG)", ln=1, align="C")
    pdf.cell(200, 10, txt=f"Datum: {heute}", ln=1)
    pdf.ln(10)
    
    pdf.cell(100, 10, txt="Von:", ln=1)
    pdf.cell(100, 10, txt="DEIN NAME / DEIN STUDIO", ln=1)
    pdf.cell(100, 10, txt="DEINE ADRESSE", ln=1)
    
    pdf.ln(5)
    pdf.cell(100, 10, txt="An:", ln=1)
    pdf.cell(100, 10, txt=f"{kunde}", ln=1)
    pdf.cell(100, 10, txt=f"{ort}", ln=1)
    
    pdf.ln(10)
    pdf.cell(80, 10, txt="Leistung:", ln=1)
    pdf.cell(120, 10, txt=f"{leistung}", ln=1)
    pdf.cell(80, 10, txt="Betrag:", ln=1)
    pdf.cell(120, 10, txt=f"{preis.replace('€', 'EUR')}", ln=1)
    
    pdf.ln(10)
    pdf.cell(200, 10, txt="Keine Umsatzsteuer gem. § 19 UStG", ln=1, align="C")
    
    pdf_path = f"rechnung_{kunde.replace(' ', '_')}.pdf"
    pdf.output(pdf_path)
    return pdf_path

def main():
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("rechnung", rechnung))
    app.add_handler(CommandHandler("liste", liste))
    app.add_handler(CommandHandler("delete", delete))
    app.add_handler(CommandHandler("export", export))
    app.run_polling()

if __name__ == "__main__":
    main()
