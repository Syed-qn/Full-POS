"""Fixed structural label translations (English/Arabic) for the tax-invoice / receipt output.

Only the FIXED structural labels are translated here (headings, section titles).
Dynamic data — dish names, customer names, restaurant name, addresses — is never
machine-translated: doing that correctly requires a real translation vendor, which
is explicitly out of scope for this platform right now.

Real UAE Ministry of Finance e-invoicing (ASP transmission) is a separate, out-of-scope
concern — this module only affects the human-readable bilingual label set returned
alongside the existing tax-invoice JSON (see app.ordering.tax.build_tax_invoice).
"""

RECEIPT_LABELS_EN: dict[str, str] = {
    "title": "Tax Invoice",
    "invoice_number": "Invoice Number",
    "trn": "TRN",
    "line_items": "Items",
    "qty": "Qty",
    "price": "Price",
    "subtotal": "Subtotal",
    "delivery_fee": "Delivery Fee",
    "vat": "VAT",
    "total": "Total",
}

RECEIPT_LABELS_AR: dict[str, str] = {
    "title": "فاتورة ضريبية",
    "invoice_number": "رقم الفاتورة",
    "trn": "الرقم الضريبي",
    "line_items": "الأصناف",
    "qty": "الكمية",
    "price": "السعر",
    "subtotal": "المجموع الفرعي",
    "delivery_fee": "رسوم التوصيل",
    "vat": "ضريبة القيمة المضافة",
    "total": "الإجمالي",
}


def bilingual_labels() -> dict[str, dict[str, str]]:
    """Return ``{"en": {...}, "ar": {...}}`` fixed structural labels for receipt templates.

    Both dicts share the same key set (structural fields), so a template can pick
    a language and iterate the same keys either way.
    """
    return {"en": dict(RECEIPT_LABELS_EN), "ar": dict(RECEIPT_LABELS_AR)}
