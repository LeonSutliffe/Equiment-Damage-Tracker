"""Lookup by barcode, serial number or ticket number (architecture 5.1)."""

import re
from dataclasses import dataclass, field

from django.db.models import Q

from .models import Item, Ticket

TICKET_RE = re.compile(r"^\s*t\s*-?\s*0*(\d+)\s*$", re.IGNORECASE)
DIGITS_RE = re.compile(r"^\s*0*(\d+)\s*$")


@dataclass
class SearchResult:
    query: str
    ticket: Ticket | None = None
    item: Item | None = None
    items: list = field(default_factory=list)
    tickets: list = field(default_factory=list)


def search(raw_query):
    query = (raw_query or "").strip()
    result = SearchResult(query=query)
    if not query:
        return result

    # "T-00042", "t42", "T 42": definitely a ticket number.
    match = TICKET_RE.match(query)
    if match:
        result.ticket = Ticket.objects.filter(number=int(match.group(1))).first()
        if result.ticket:
            return result

    # An exact barcode or serial number wins over a bare ticket number, since
    # barcodes are usually all digits.
    exact = list(
        Item.objects.select_related("item_type").filter(Q(barcode__iexact=query) | Q(serial_number__iexact=query))
    )
    if len(exact) == 1:
        result.item = exact[0]
        return result
    if len(exact) > 1:
        result.items = exact
        return result

    match = DIGITS_RE.match(query)
    if match and len(match.group(1)) <= 7:
        result.ticket = Ticket.objects.filter(number=int(match.group(1))).first()
        if result.ticket:
            return result

    # Partial match on barcode/serial, or an item type name.
    result.items = list(
        Item.objects.select_related("item_type")
        .filter(Q(barcode__icontains=query) | Q(serial_number__icontains=query) | Q(item_type__name__icontains=query))
        .order_by("item_type__name", "serial_number")[:50]
    )
    # Tickets whose previous job matches (e.g. "Glastonbury").
    if len(query) >= 2:
        result.tickets = list(
            Ticket.objects.select_related("item__item_type").filter(previous_job__icontains=query).order_by("-number")[:50]
        )
    return result
