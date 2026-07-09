"""Fixed structural label translations (English/Arabic) for tax invoices / receipts.

Only FIXED structural labels are translated. Dynamic data (dish names, etc.) is never
machine-translated.
"""

from __future__ import annotations

RECEIPT_LABELS_EN: dict[str, str] = {
    "title": "Tax Invoice",
    "title_simplified": "Simplified Tax Invoice",
    "title_refund": "Refund Note",
    "title_credit": "Credit Note",
    "invoice_number": "Invoice Number",
    "refund_note_number": "Refund Note Number",
    "credit_note_number": "Credit Note Number",
    "trn": "TRN",
    "buyer_trn": "Buyer TRN",
    "line_items": "Items",
    "qty": "Qty",
    "price": "Price",
    "subtotal": "Subtotal",
    "taxable": "Taxable Amount",
    "delivery_fee": "Delivery Fee",
    "vat": "VAT",
    "vat_breakdown": "VAT Breakdown",
    "total": "Total",
    "tax_inclusive": "Prices include VAT",
    "tax_exclusive": "Prices exclude VAT",
}

RECEIPT_LABELS_AR: dict[str, str] = {
    "title": "فاتورة ضريبية",
    "title_simplified": "فاتورة ضريبية مبسطة",
    "title_refund": "إشعار استرداد",
    "title_credit": "إشعار دائن",
    "invoice_number": "رقم الفاتورة",
    "refund_note_number": "رقم إشعار الاسترداد",
    "credit_note_number": "رقم إشعار الدائن",
    "trn": "الرقم الضريبي",
    "buyer_trn": "الرقم الضريبي للمشتري",
    "line_items": "الأصناف",
    "qty": "الكمية",
    "price": "السعر",
    "subtotal": "المجموع الفرعي",
    "taxable": "المبلغ الخاضع للضريبة",
    "delivery_fee": "رسوم التوصيل",
    "vat": "ضريبة القيمة المضافة",
    "vat_breakdown": "تفصيل ضريبة القيمة المضافة",
    "total": "الإجمالي",
    "tax_inclusive": "الأسعار تشمل ضريبة القيمة المضافة",
    "tax_exclusive": "الأسعار لا تشمل ضريبة القيمة المضافة",
}


def bilingual_labels() -> dict[str, dict[str, str]]:
    return {"en": dict(RECEIPT_LABELS_EN), "ar": dict(RECEIPT_LABELS_AR)}


def invoice_labels(document_type: str = "tax_invoice") -> dict[str, dict[str, str]]:
    """Return bilingual labels with the correct title for document type."""
    en = dict(RECEIPT_LABELS_EN)
    ar = dict(RECEIPT_LABELS_AR)
    if document_type == "simplified_tax_invoice":
        en["title"] = RECEIPT_LABELS_EN["title_simplified"]
        ar["title"] = RECEIPT_LABELS_AR["title_simplified"]
    elif document_type == "refund_note":
        en["title"] = RECEIPT_LABELS_EN["title_refund"]
        ar["title"] = RECEIPT_LABELS_AR["title_refund"]
    elif document_type == "credit_note":
        en["title"] = RECEIPT_LABELS_EN["title_credit"]
        ar["title"] = RECEIPT_LABELS_AR["title_credit"]
    return {"en": en, "ar": ar}
