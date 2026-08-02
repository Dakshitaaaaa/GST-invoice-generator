import streamlit as st
import pandas as pd
import io
from datetime import datetime
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch

# ------------------------------------------------------------------
# SESSION STATE INITIALIZATION (Local Ledger for Duplicate Check)
# ------------------------------------------------------------------
if "generated_invoices" not in st.session_state:
    st.session_state.generated_invoices = set()

# ------------------------------------------------------------------
# CA COMPLIANCE LOGIC: Validation & Tax Calculation
# ------------------------------------------------------------------
def validate_gstin(supplier_gstin, recipient_gstin):
    """GST Law Rule: A entity cannot issue a tax invoice to its own GSTIN."""
    if supplier_gstin.strip().upper() == recipient_gstin.strip().upper():
        return False, "⚠️ Compliance Error: Supplier GSTIN and Recipient GSTIN cannot be identical."
    return True, ""

def calculate_gst(taxable_value, gst_rate, supplier_state, recipient_state, doc_type):
    """Calculates CGST, SGST, IGST based on POS & Document Type."""
    if doc_type == "Bill of Supply":
        gst_rate = 0.0  # Bill of supply cannot carry tax
        
    taxable_value = float(taxable_value)
    gst_rate = float(gst_rate)
    
    if supplier_state.strip().lower() == recipient_state.strip().lower():
        cgst_rate, sgst_rate, igst_rate = gst_rate / 2, gst_rate / 2, 0.0
        cgst_amt = round(taxable_value * (cgst_rate / 100), 2)
        sgst_amt = round(taxable_value * (sgst_rate / 100), 2)
        igst_amt = 0.0
    else:
        cgst_rate, sgst_rate, igst_rate = 0.0, 0.0, gst_rate
        cgst_amt, sgst_amt = 0.0, 0.0
        igst_amt = round(taxable_value * (igst_rate / 100), 2)
        
    total_tax = cgst_amt + sgst_amt + igst_amt
    total_amount = taxable_value + total_tax
    
    return {
        "cgst_rate": cgst_rate, "cgst_amt": cgst_amt,
        "sgst_rate": sgst_rate, "sgst_amt": sgst_amt,
        "igst_rate": igst_rate, "igst_amt": igst_amt,
        "total_tax": total_tax, "total_amount": total_amount
    }

def generate_pdf_invoice(data):
    """Generates PDF for Tax Invoice / Bill of Supply / Credit Note / Debit Note."""
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, rightMargin=30, leftMargin=30, topMargin=30, bottomMargin=30)
    story = []
    styles = getSampleStyleSheet()
    
    title_style = ParagraphStyle('TitleStyle', parent=styles['Heading1'], fontSize=16, leading=20, alignment=1)
    normal_style = ParagraphStyle('NormalStyle', parent=styles['Normal'], fontSize=9, leading=12)

    # 1. Header Title
    doc_header = data['doc_type'].upper()
    story.append(Paragraph(f"<b>{doc_header}</b>", title_style))
    story.append(Spacer(1, 10))

    # Meta Section
    meta_info = f"<b>Document No:</b> {data['inv_no']}<br/><b>Date:</b> {data['inv_date']}<br/><b>Place of Supply:</b> {data['recipient_state']}"
    if data['doc_type'] in ["Credit Note", "Debit Note"]:
        meta_info += f"<br/><b>Original Inv No:</b> {data['orig_inv_no']}<br/><b>Original Inv Date:</b> {data['orig_inv_date']}"

    # 2. Table Header
    header_data = [
        [
            Paragraph(f"<b>SUPPLIER:</b><br/><b>{data['supplier_name']}</b><br/>{data['supplier_addr']}<br/><b>GSTIN:</b> {data['supplier_gstin']}<br/><b>State:</b> {data['supplier_state']}", normal_style),
            Paragraph(meta_info, normal_style)
        ],
        [
            Paragraph(f"<b>RECIPIENT (BILLED TO):</b><br/><b>{data['recipient_name']}</b><br/>{data['recipient_addr']}<br/><b>GSTIN:</b> {data['recipient_gstin']}<br/><b>State:</b> {data['recipient_state']}", normal_style),
            ""
        ]
    ]
    t_header = Table(header_data, colWidths=[3.75 * inch, 3.75 * inch])
    t_header.setStyle(TableStyle([
        ('BOX', (0,0), (-1,-1), 1, colors.black),
        ('INNERGRID', (0,0), (-1,-1), 0.5, colors.grey),
        ('VALIGN', (0,0), (-1,-1), 'TOP'),
        ('SPAN', (0,1), (1,1)),
    ]))
    story.append(t_header)
    story.append(Spacer(1, 15))

    # 3. Line Items Table
    is_intra = data['tax_calc']['cgst_amt'] > 0
    is_bill_of_supply = data['doc_type'] == "Bill of Supply"

    if is_bill_of_supply:
        table_data = [["HSN/SAC", "Description", "Qty", "Rate (₹)", "Taxable Value (₹)", "Total Amount (₹)"]]
    elif is_intra:
        table_data = [["HSN/SAC", "Description", "Qty", "Rate (₹)", "Taxable Val (₹)", "CGST", "SGST", "Total (₹)"]]
    else:
        table_data = [["HSN/SAC", "Description", "Qty", "Rate (₹)", "Taxable Val (₹)", "IGST", "Total (₹)"]]

    row = [str(data['hsn']), data['item_desc'], str(data['qty']), f"{float(data['rate']):.2f}", f"{float(data['taxable_value']):.2f}"]
    tc = data['tax_calc']
    
    if not is_bill_of_supply:
        if is_intra:
            row.append(f"{tc['cgst_rate']}% ({tc['cgst_amt']:.2f})")
            row.append(f"{tc['sgst_rate']}% ({tc['sgst_amt']:.2f})")
        else:
            row.append(f"{tc['igst_rate']}% ({tc['igst_amt']:.2f})")
            
    row.append(f"{tc['total_amount']:.2f}")
    table_data.append(row)

    t_items = Table(table_data)
    t_items.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), colors.lightgrey),
        ('ALIGN', (0,0), (-1,-1), 'CENTER'),
        ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
        ('FONTSIZE', (0,0), (-1,-1), 8),
        ('BOX', (0,0), (-1,-1), 1, colors.black),
        ('INNERGRID', (0,0), (-1,-1), 0.5, colors.grey),
    ]))
    story.append(t_items)
    story.append(Spacer(1, 15))

    # 4. Summary Table
    summary_data = [["Total Value:", f"₹ {data['taxable_value']:.2f}"]]
    if not is_bill_of_supply:
        if is_intra:
            summary_data.append(["CGST Total:", f"₹ {tc['cgst_amt']:.2f}"])
            summary_data.append(["SGST Total:", f"₹ {tc['sgst_amt']:.2f}"])
        else:
            summary_data.append(["IGST Total:", f"₹ {tc['igst_amt']:.2f}"])
            
    summary_data.append(["Grand Total:", f"₹ {tc['total_amount']:.2f}"])

    t_summary = Table(summary_data, colWidths=[5.5 * inch, 2.0 * inch])
    t_summary.setStyle(TableStyle([
        ('ALIGN', (0,0), (-1,-1), 'RIGHT'),
        ('FONTNAME', (0,-1), (-1,-1), 'Helvetica-Bold'),
        ('LINEABOVE', (0,-1), (-1,-1), 1, colors.black),
    ]))
    story.append(t_summary)
    story.append(Spacer(1, 25))

    # Footer
    footer_data = [[
        Paragraph("<b>Declaration:</b> We declare that this invoice shows the actual price of the goods/services described.", normal_style),
        Paragraph(f"For <b>{data['supplier_name']}</b><br/><br/><br/>Authorized Signatory", ParagraphStyle('RightText', parent=normal_style, alignment=2))
    ]]
    t_footer = Table(footer_data, colWidths=[4.5 * inch, 3.0 * inch])
    story.append(t_footer)

    doc.build(story)
    buffer.seek(0)
    return buffer

# ------------------------------------------------------------------
# STREAMLIT UI LAYOUT
# ------------------------------------------------------------------
st.set_page_config(page_title="GST Document Generator", layout="wide")
st.title("📄 Tax Invoice, Credit/Debit Note & Bill of Supply Generator")

doc_type = st.selectbox("Select Statutory Document Type", ["Tax Invoice", "Bill of Supply", "Credit Note", "Debit Note"])

col1, col2 = st.columns(2)
with col1:
    st.markdown("### Supplier Details")
    supplier_name = st.text_input("Supplier Name", "ABC Enterprises Pvt Ltd")
    supplier_gstin = st.text_input("Supplier GSTIN", "24AAAAA0000A1Z5")
    supplier_state = st.text_input("Supplier State", "Gujarat")
    supplier_addr = st.text_area("Supplier Address", "101, Business Hub, Ahmedabad")

with col2:
    st.markdown("### Recipient Details")
    recipient_name = st.text_input("Recipient Name", "XYZ Tech Solutions")
    recipient_gstin = st.text_input("Recipient GSTIN", "27BBBBB1111B1Z2")
    recipient_state = st.text_input("Recipient State (POS)", "Maharashtra")
    recipient_addr = st.text_area("Recipient Address", "202, Tech Park, Mumbai")

st.markdown("---")
c1, c2, c3 = st.columns(3)
with c1:
    inv_no = st.text_input("Document / Invoice Number", "INV/2026-27/001")
    inv_date = st.date_input("Document Date", datetime.now()).strftime("%d-%m-%Y")
    
    orig_inv_no, orig_inv_date = "", ""
    if doc_type in ["Credit Note", "Debit Note"]:
        orig_inv_no = st.text_input("Original Invoice Reference No.")
        orig_inv_date = st.date_input("Original Invoice Date", datetime.now()).strftime("%d-%m-%Y")

with c2:
    hsn = st.text_input("HSN / SAC Code", "998311")
    item_desc = st.text_input("Item Description", "Software Consulting")

with c3:
    qty = st.number_input("Quantity", min_value=1.0, value=1.0)
    rate = st.number_input("Unit Rate (₹)", min_value=0.0, value=10000.0)
    gst_rate = st.selectbox("GST Rate (%)", [0, 5, 12, 18, 28], index=3, disabled=(doc_type == "Bill of Supply"))

# PRE-SUBMISSION VALIDATION CHECKS
is_gstin_valid, gstin_err_msg = validate_gstin(supplier_gstin, recipient_gstin)
if not is_gstin_valid:
    st.error(gstin_err_msg)

is_duplicate_inv = inv_no in st.session_state.generated_invoices
if is_duplicate_inv:
    st.error(f"❌ Compliance Warning: Document/Invoice Number '{inv_no}' has already been generated! GST rules prohibit duplicate invoice numbers within the same financial year.")

taxable_val = qty * rate
calc = calculate_gst(taxable_val, gst_rate, supplier_state, recipient_state, doc_type)

payload = {
    "doc_type": doc_type, "supplier_name": supplier_name, "supplier_gstin": supplier_gstin,
    "supplier_state": supplier_state, "supplier_addr": supplier_addr, "recipient_name": recipient_name,
    "recipient_gstin": recipient_gstin, "recipient_state": recipient_state, "recipient_addr": recipient_addr,
    "inv_no": inv_no, "inv_date": inv_date, "orig_inv_no": orig_inv_no, "orig_inv_date": orig_inv_date,
    "hsn": hsn, "item_desc": item_desc, "qty": qty, "rate": rate, "taxable_value": taxable_val, "tax_calc": calc
}

# DISABLE BUTTON IF COMPLIANCE Fails
button_disabled = (not is_gstin_valid) or is_duplicate_inv

if st.button("Generate GST Document", type="primary", disabled=button_disabled):
    # Log Invoice No to avoid duplicates during session
    st.session_state.generated_invoices.add(inv_no)
    
    pdf_file = generate_pdf_invoice(payload)
    st.success(f"{doc_type} generated successfully!")
    st.download_button(
        label=f"⬇️ Download {doc_type} PDF",
        data=pdf_file,
        file_name=f"{inv_no.replace('/', '_')}.pdf",
        mime="application/pdf"
    )