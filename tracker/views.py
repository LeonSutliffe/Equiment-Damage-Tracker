from django.contrib import messages
from django.contrib.auth.decorators import login_not_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Case, Count, IntegerField, Q, Sum, Value, When
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme, urlencode
from django.views.decorators.http import require_POST

from accounts.audit import record
from accounts.permissions import require_perm

from . import deletion
from .forms import (
    BulkTicketForm,
    DocumentForm,
    ItemForm,
    ItemTypeForm,
    TicketForm,
    WriteOffForm,
)
from .models import (
    Comment,
    CommentEdit,
    Document,
    FieldChange,
    Item,
    ItemChange,
    ItemType,
    Photo,
    Ticket,
)
from .search import search
from .services import (
    ConflictError,
    create_item,
    create_ticket,
    reinstate_item,
    remove_photo,
    update_item,
    update_ticket,
    write_off_item,
)

OPEN_STATUSES = [Ticket.Status.OPEN, Ticket.Status.IN_PROGRESS]


# ---------------------------------------------------------------- lookup


@require_perm("view")
def home(request):
    query = request.GET.get("q", "")
    result = search(query) if query.strip() else None
    if result:
        if result.ticket:
            return redirect("ticket_detail", number=result.ticket.number)
        if result.item:
            return redirect("item_detail", pk=result.item.pk)
    open_count = Ticket.objects.filter(status__in=OPEN_STATUSES).count()
    return render(request, "tracker/home.html", {"result": result, "query": query, "open_count": open_count})


# ---------------------------------------------------------------- items


@require_perm("view")
def item_list(request):
    items = Item.objects.select_related("item_type").annotate(
        open_tickets=Count("tickets", filter=Q(tickets__status__in=OPEN_STATUSES)),
        all_tickets=Count("tickets"),
    )
    type_id = request.GET.get("type")
    if type_id and type_id.isdigit():
        items = items.filter(item_type_id=type_id)
    state = request.GET.get("state", "in_use")
    if state == "in_use":
        items = items.filter(written_off_at__isnull=True)
    elif state == "written_off":
        items = items.filter(written_off_at__isnull=False)
    page = Paginator(items, 50).get_page(request.GET.get("page"))
    return render(
        request,
        "tracker/item_list.html",
        {"page": page, "item_types": ItemType.objects.all(), "type_id": type_id or "", "state": state,
         "filter_query": urlencode({k: v for k, v in (("type", type_id or ""), ("state", state)) if v})},
    )


@require_perm("view")
def item_detail(request, pk):
    item = get_object_or_404(Item.objects.select_related("item_type", "written_off_by"), pk=pk)
    tickets = item.tickets.all().order_by("-created_at")
    documents = Document.objects.filter(removed_at__isnull=True).filter(
        Q(item=item) | Q(item_type_id=item.item_type_id)
    ).order_by("item_id", "title")  # type documents first
    doc_form = DocumentForm(item=item) if request.user.can("manage_documents") else None
    return render(request, "tracker/item_detail.html", {"item": item, "tickets": tickets, "documents": documents,
                                                         "doc_form": doc_form, "doc_max_mb": _doc_max_mb()})


def _doc_max_mb():
    from django.conf import settings

    return settings.DOCUMENT_MAX_UPLOAD_BYTES // (1024 * 1024)


@require_perm("view")
def item_timeline(request, pk):
    """Everything that ever happened to one item, newest first, with a summary."""
    item = get_object_or_404(Item.objects.select_related("item_type", "created_by"), pk=pk)
    tickets = list(item.tickets.all().order_by("created_at"))
    by_id = {t.pk: t for t in tickets}
    events = []

    def add(when, who, kind, text, ticket=None):
        events.append({"when": when, "who": who.label if who else "", "kind": kind, "text": text, "ticket": ticket})

    add(item.created_at, item.created_by, "item", "Item added")
    for c in ItemChange.objects.filter(item=item).select_related("user"):
        if c.field == "write_off":
            add(c.changed_at, c.user, "writeoff", c.new_value if c.new_value != "Back in use" else "Put back in use")
        elif c.old_value or c.changed_at != item.created_at:
            add(c.changed_at, c.user, "item",
                f"{Item.TRACKED_FIELDS.get(c.field, c.field)} changed from {c.old_value or '(blank)'} to {c.new_value or '(blank)'}")
    for t in tickets:
        desc = f": {t.fault_description}" if t.fault_description else ""
        if t.previous_job:
            desc += f" (previous job: {t.previous_job})"
        add(t.created_at, t.created_by, "opened",
            f"Fault logged, {t.get_fault_type_display()}, {t.get_severity_display()} severity{desc}", t)
    changes = FieldChange.objects.filter(ticket__in=tickets).exclude(note="created").select_related("user")
    for c in changes:
        t = by_id[c.ticket_id]
        label = Ticket.TRACKED_FIELDS.get(c.field, c.field)
        if c.field == "photos":
            text = f"Photo {c.note}"
        elif c.field in ("fault_description", "work_done"):
            text = f"{label}: {c.new_value}" if c.new_value else f"{label} cleared"
        else:
            old, new = t.display_value(c.field, c.old_value), t.display_value(c.field, c.new_value)
            text = f"{label} changed from {old or '(blank)'} to {new or '(blank)'}"
        kind = "resolved" if c.field == "status" and c.new_value == Ticket.Status.RESOLVED else "change"
        add(c.changed_at, c.user, kind, text, t)
    for c in Comment.objects.filter(ticket__in=tickets).select_related("user", "removed_by"):
        t = by_id[c.ticket_id]
        if c.removed_at:
            add(c.created_at, c.user, "comment", f"Comment (since removed): {c.text}", t)
            add(c.removed_at, c.removed_by, "removed", f"Comment by {c.user.label if c.user else '(deleted user)'} removed", t)
        else:
            add(c.created_at, c.user, "comment", f"Comment{' (edited)' if c.edited_at else ''}: {c.text}", t)
    for e in CommentEdit.objects.filter(comment__ticket__in=tickets).select_related("user", "comment"):
        add(e.edited_at, e.user, "comment", f"Comment edited: “{e.old_text}” → “{e.new_text}”", by_id[e.comment.ticket_id])
    events.sort(key=lambda e: e["when"], reverse=True)

    fault_counts = {}
    for t in tickets:
        fault_counts[t.get_fault_type_display()] = fault_counts.get(t.get_fault_type_display(), 0) + 1
    totals = item.tickets.aggregate(cost=Sum("repair_cost"), hours=Sum("repair_time"))
    total_cost = totals["cost"]
    summary = {
        "tickets": len(tickets),
        "open": sum(1 for t in tickets if t.status in OPEN_STATUSES),
        "faults": sorted(fault_counts.items()),
        "total_cost": total_cost,
        "total_hours": totals["hours"],
        "first": tickets[0].created_at if tickets else None,
        "last": tickets[-1].created_at if tickets else None,
    }
    return render(request, "tracker/item_timeline.html", {"item": item, "events": events, "summary": summary,
                                                           "tickets": tickets[::-1]})


@require_perm("write_off_item")
def item_write_off(request, pk):
    item = get_object_or_404(Item.objects.select_related("item_type"), pk=pk)
    if item.is_written_off:
        messages.info(request, "This item is already written off.")
        return redirect("item_detail", pk=item.pk)
    form = WriteOffForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        write_off_item(item, request.user, form.cleaned_data["reason"])
        record(request, "item", f"Wrote off {item} (barcode {item.barcode}): {form.cleaned_data['reason']}",
               reverse("item_detail", args=[item.pk]))
        messages.success(request, f"{item} written off. Its history is kept.")
        return redirect("item_detail", pk=item.pk)
    open_list = item.tickets.filter(status__in=OPEN_STATUSES)
    return render(request, "tracker/item_write_off.html", {"item": item, "form": form, "open_tickets": open_list})


@require_POST
@require_perm("write_off_item")
def item_reinstate(request, pk):
    item = get_object_or_404(Item, pk=pk)
    if item.is_written_off:
        reinstate_item(item, request.user)
        record(request, "item", f"Put {item} (barcode {item.barcode}) back in use", reverse("item_detail", args=[item.pk]))
        messages.success(request, f"{item} is back in use.")
    return redirect("item_detail", pk=item.pk)


@require_perm("create_item")
def item_create(request):
    initial = {k: request.GET[k] for k in ("barcode", "serial_number") if request.GET.get(k)}
    form = ItemForm(request.POST or None, initial=initial)
    if request.method == "POST" and form.is_valid():
        item = create_item(request.user, form.cleaned_data)
        record(request, "item", f"Added item {item} (barcode {item.barcode})", reverse("item_detail", args=[item.pk]))
        messages.success(request, f"Item {item} created.")
        if request.user.can("create_ticket"):
            return redirect("ticket_create", item_pk=item.pk)
        return redirect("item_detail", pk=item.pk)
    no_types = not ItemType.objects.filter(active=True).exists()
    return render(request, "tracker/item_form.html", {"form": form, "title": "Create item", "no_types": no_types})


@require_perm("edit_item")
def item_edit(request, pk):
    item = get_object_or_404(Item, pk=pk)
    form = ItemForm(request.POST or None, instance=item)
    if request.method == "POST" and form.is_valid():
        changed = [Item.TRACKED_FIELDS[f] for f in form.changed_data if f in Item.TRACKED_FIELDS]
        update_item(form.instance, request.user, form.cleaned_data)
        if changed:
            record(request, "item", f"Edited item {item} (barcode {item.barcode}): {', '.join(changed)}",
                   reverse("item_detail", args=[item.pk]))
        messages.success(request, "Item saved.")
        return redirect("item_detail", pk=item.pk)
    return render(request, "tracker/item_form.html", {"form": form, "title": f"Edit {item}", "item": item})


@require_perm("view")
def item_history(request, pk, field):
    item = get_object_or_404(Item, pk=pk)
    if field not in Item.HISTORY_FIELDS:
        raise Http404
    changes = ItemChange.objects.filter(item=item, field=field).select_related("user")
    return render(
        request,
        "tracker/history_popup.html",
        {"label": Item.HISTORY_FIELDS[field], "field": field, "entries": [_entry(c, c.old_value, c.new_value) for c in changes]},
    )


# ---------------------------------------------------------------- tickets


@require_perm("create_ticket")
def ticket_create(request, item_pk):
    item = get_object_or_404(Item.objects.select_related("item_type"), pk=item_pk)
    if item.is_written_off:
        messages.error(request, f"{item} has been written off, so new faults can't be logged on it.")
        return redirect("item_detail", pk=item.pk)
    form = TicketForm(request.POST or None, request.FILES or None, creating=True)
    if request.method == "POST" and form.is_valid():
        try:
            ticket = create_ticket(item, request.user, form.cleaned_data, form.cleaned_data.get("photos", []))
        except ValidationError as exc:
            form.add_error("photos", exc)
        else:
            record(request, "ticket",
                   f"Opened {ticket.code} on {item} (barcode {item.barcode}): {ticket.get_fault_type_display()}, "
                   f"{ticket.get_severity_display()}", reverse("ticket_detail", args=[ticket.number]))
            messages.success(request, f"Ticket {ticket.code} created.")
            return redirect("ticket_detail", number=ticket.number)
    # Duplicate warning: show any tickets already open on this item.
    already_open = item.tickets.filter(status__in=OPEN_STATUSES).order_by("-created_at")
    return render(request, "tracker/ticket.html", {"form": form, "item": item, "ticket": None, "can_edit": True,
                                                   "already_open": already_open})


@require_perm("view")
def ticket_detail(request, number):
    ticket = get_object_or_404(Ticket.objects.select_related("item__item_type"), number=number)
    can_edit = request.user.can("edit_ticket")
    conflict = None

    if request.method == "POST":
        if not can_edit:
            raise PermissionDenied("Your role can't edit tickets.")
        form = TicketForm(request.POST, request.FILES, instance=Ticket.objects.get(pk=ticket.pk))
        if form.is_valid():
            data = {f: form.cleaned_data[f] for f in
                    ("status", "fault_type", "severity", "previous_job", "fault_description", "work_done", "repair_cost",
                     "repair_time")}
            try:
                ticket, changed = update_ticket(
                    ticket, request.user, data, form.cleaned_data.get("version") or 0, form.cleaned_data.get("photos", [])
                )
            except ConflictError:
                # Someone else saved first: show the latest version and what this user typed.
                conflict = {
                    Ticket.TRACKED_FIELDS[f]: ticket.display_value(f, v) for f, v in data.items() if v not in ("", None)
                }
                ticket.refresh_from_db()
            except ValidationError as exc:
                form.add_error("photos", exc)
            else:
                if changed:
                    record(request, "ticket", f"{ticket.code}: {'; '.join(changed)}",
                           reverse("ticket_detail", args=[ticket.number]))
                messages.success(request, f"{ticket.code} saved." if changed else "Nothing changed.")
                return redirect("ticket_detail", number=ticket.number)
        if conflict is None and form.errors:
            return render(request, "tracker/ticket.html", _ticket_context(request, ticket, form, can_edit))

    form = TicketForm(instance=ticket, initial={"version": ticket.version})
    if not can_edit:
        for f in form.fields.values():
            f.disabled = True
    ctx = _ticket_context(request, ticket, form, can_edit)
    ctx["conflict"] = conflict
    return render(request, "tracker/ticket.html", ctx)


def _ticket_context(request, ticket, form, can_edit):
    photos = ticket.photos.filter(removed_at__isnull=True)
    comments = ticket.comments.select_related("user", "removed_by")
    return {"form": form, "ticket": ticket, "item": ticket.item, "photos": photos, "can_edit": can_edit,
            "comments": comments}


@require_POST
@require_perm("edit_ticket")
def comment_add(request, number):
    ticket = get_object_or_404(Ticket, number=number)
    text = request.POST.get("text", "").strip()
    if text:
        Comment.objects.create(ticket=ticket, user=request.user, text=text[:5000])
        Ticket.objects.filter(pk=ticket.pk).update(updated_at=timezone.now())
        record(request, "comment", f"Commented on {ticket.code}: {text[:200]}", reverse("ticket_detail", args=[ticket.number]))
        messages.success(request, "Comment added.")
    return redirect(reverse("ticket_detail", args=[ticket.number]) + "#comments")


@require_POST
@require_perm("edit_ticket")
def comment_edit(request, pk):
    """People can edit their own comments. Every earlier version is kept and shown."""
    comment = get_object_or_404(Comment.objects.select_related("ticket"), pk=pk)
    if comment.user_id != request.user.pk or comment.removed_at:
        raise PermissionDenied("You can only edit your own comments.")
    text = request.POST.get("text", "").strip()[:5000]
    back = reverse("ticket_detail", args=[comment.ticket.number]) + f"#comment-{comment.pk}"
    if text and text != comment.text:
        now = timezone.now()
        with transaction.atomic():
            CommentEdit.objects.create(comment=comment, old_text=comment.text, new_text=text, user=request.user,
                                       edited_at=now)
            Comment.objects.filter(pk=comment.pk).update(text=text, edited_at=now)
        record(request, "comment", f"Edited a comment on {comment.ticket.code}: {text[:200]}", back)
        messages.success(request, "Comment updated. The earlier version is kept in its history.")
    return redirect(back)


@require_perm("view")
def comment_history(request, pk):
    comment = get_object_or_404(Comment.objects.select_related("user"), pk=pk)
    edits = list(comment.edits.select_related("user").order_by("edited_at", "id"))
    versions = [{"when": comment.created_at, "who": comment.user, "text": edits[0].old_text if edits else comment.text,
                 "note": "written"}]
    versions += [{"when": e.edited_at, "who": e.user, "text": e.new_text, "note": "edited"} for e in edits]
    return render(request, "tracker/comment_history.html", {"comment": comment, "versions": versions[::-1]})


@require_POST
@require_perm("delete_records")
def comment_remove(request, pk):
    comment = get_object_or_404(Comment.objects.select_related("ticket", "user"), pk=pk)
    ticket = comment.ticket
    url = reverse("ticket_detail", args=[ticket.number])
    who = comment.user.label if comment.user else "(deleted user)"
    if deletion.can_delete_permanently(request.user):
        deletion.delete_comment(comment)
        record(request, "deletion", f"Permanently deleted a comment by {who} on {ticket.code}: {comment.text[:200]}", url)
        messages.success(request, "Comment permanently deleted.")
    elif not comment.removed_at:
        deletion.remove_comment(comment, request.user)
        record(request, "comment", f"Removed a comment by {who} on {ticket.code}: {comment.text[:200]}", url)
        messages.success(request, "Comment removed. A note stays in its place and in the item history.")
    return redirect(url + "#comments")


def _require_permanent_delete(request):
    if not deletion.can_delete_permanently(request.user):
        raise PermissionDenied("Switch on “Allow permanent deletions” in your Settings first.")


@require_perm("delete_records")
def ticket_delete(request, number):
    ticket = get_object_or_404(Ticket.objects.select_related("item__item_type"), number=number)
    _require_permanent_delete(request)
    cancel = reverse("ticket_detail", args=[ticket.number])
    summary = deletion.ticket_summary(ticket)
    missing = request.method == "POST" and not request.POST.get("confirm")
    if request.method == "POST" and not missing:
        code, item = ticket.code, ticket.item
        deletion.delete_ticket(ticket)
        record(request, "deletion", f"Permanently deleted {code} on {item} ({item.barcode}), with "
               f"{summary['photos']} photo(s), {summary['comments']} comment(s) and {summary['changes']} history entries",
               reverse("item_detail", args=[item.pk]))
        messages.success(request, f"{code} permanently deleted.")
        return redirect("item_detail", pk=item.pk)
    return render(request, "tracker/confirm_delete.html", {
        "title": f"Delete {ticket.code}", "what": f"{ticket.code} on {ticket.item.item_type} ({ticket.item.barcode})",
        "summary": [f"{summary['photos']} photo(s)", f"{summary['comments']} comment(s)",
                    f"{summary['changes']} field history entries"],
        "cancel": cancel, "missing": missing, "is_item": False,
    })


@require_perm("delete_records")
def item_delete(request, pk):
    item = get_object_or_404(Item.objects.select_related("item_type"), pk=pk)
    _require_permanent_delete(request)
    summary = deletion.item_summary(item)
    missing = request.method == "POST" and not request.POST.get("confirm")
    if request.method == "POST" and not missing:
        label = f"{item.item_type} (barcode {item.barcode}, serial {item.serial_number})"
        deletion.delete_item(item)
        record(request, "deletion", f"Permanently deleted item {label}, with {summary['tickets']} ticket(s), "
               f"{summary['photos']} photo(s) and {summary['documents']} document(s)")
        messages.success(request, f"{label} permanently deleted.")
        return redirect("item_list")
    return render(request, "tracker/confirm_delete.html", {
        "title": "Delete item", "what": f"{item.item_type} (barcode {item.barcode}, serial {item.serial_number})",
        "summary": [f"{summary['tickets']} ticket(s) and everything on them", f"{summary['photos']} photo(s)",
                    f"{summary['documents']} document(s) attached to this item only", "its whole history"],
        "cancel": reverse("item_detail", args=[item.pk]), "missing": missing, "is_item": True,
    })


def _entry(change, old, new):
    return {"when": change.changed_at, "who": change.user.label if change.user else "(deleted user)",
            "old": old, "new": new, "note": getattr(change, "note", "")}


@require_perm("view")
def ticket_history(request, number, field):
    ticket = get_object_or_404(Ticket, number=number)
    if field not in Ticket.TRACKED_FIELDS:
        raise Http404
    changes = FieldChange.objects.filter(ticket=ticket, field=field).select_related("user")
    entries = [
        _entry(c, ticket.display_value(field, c.old_value), ticket.display_value(field, c.new_value)) for c in changes
    ]
    return render(
        request,
        "tracker/history_popup.html",
        {"label": Ticket.TRACKED_FIELDS[field], "entries": entries, "field": field},
    )


# ---------------------------------------------------------------- photos


def _photo_file(photo, thumb):
    from django.conf import settings

    path = settings.PHOTOS_DIR / (photo.thumbnail_file_name if thumb else photo.file_name)
    if not path.is_file():
        raise Http404
    response = FileResponse(open(path, "rb"), content_type="image/jpeg")
    response["Cache-Control"] = "private, max-age=86400"
    return response


@require_perm("view")
def photo_view(request, pk):
    return _photo_file(get_object_or_404(Photo, pk=pk), thumb=False)


@require_perm("view")
def photo_thumb(request, pk):
    return _photo_file(get_object_or_404(Photo, pk=pk), thumb=True)


@require_POST
@require_perm("remove_photo")
def photo_remove(request, pk):
    photo = get_object_or_404(Photo.objects.select_related("ticket"), pk=pk)
    if not photo.removed_at:
        remove_photo(photo, request.user)
        record(request, "photo", f"Removed {photo.label} from {photo.ticket.code}",
               reverse("ticket_detail", args=[photo.ticket.number]))
    messages.success(request, "Photo removed from the ticket. It is kept and the removal is logged.")
    return redirect("ticket_detail", number=photo.ticket.number)


@require_POST
@require_perm("delete_records")
def photo_delete(request, pk):
    photo = get_object_or_404(Photo.objects.select_related("ticket"), pk=pk)
    _require_permanent_delete(request)
    ticket = photo.ticket
    label = photo.label
    deletion.delete_photo(photo)
    record(request, "deletion", f"Permanently deleted {label} from {ticket.code}",
           reverse("ticket_detail", args=[ticket.number]))
    messages.success(request, "Photo permanently deleted.")
    return redirect("ticket_detail", number=ticket.number)


# ---------------------------------------------------------------- lists


@require_perm("view")
def open_tickets(request):
    tickets = Ticket.objects.filter(status__in=OPEN_STATUSES).select_related("item__item_type")
    filters = {
        "fault_type": request.GET.get("fault_type", ""),
        "severity": request.GET.get("severity", ""),
        "item_type": request.GET.get("item_type", ""),
    }
    if filters["fault_type"] in Ticket.FaultType.values:
        tickets = tickets.filter(fault_type=filters["fault_type"])
    if filters["severity"] in Ticket.Severity.values:
        tickets = tickets.filter(severity=filters["severity"])
    if filters["item_type"].isdigit():
        tickets = tickets.filter(item__item_type_id=filters["item_type"])
    # Safety faults and High severity first, then oldest first (architecture 5.7).
    tickets = tickets.annotate(
        safety_rank=Case(When(fault_type=Ticket.FaultType.SAFETY, then=Value(0)), default=Value(1), output_field=IntegerField()),
        severity_rank=Case(
            When(severity=Ticket.Severity.HIGH, then=Value(0)),
            When(severity=Ticket.Severity.MEDIUM, then=Value(1)),
            default=Value(2),
            output_field=IntegerField(),
        ),
    ).order_by("safety_rank", "severity_rank", "created_at")
    page = Paginator(tickets, 100).get_page(request.GET.get("page"))
    return render(
        request,
        "tracker/open_tickets.html",
        {
            "page": page,
            "filters": filters,
            "fault_types": Ticket.FaultType.choices,
            "severities": Ticket.Severity.choices,
            "item_types": ItemType.objects.all(),
            "filter_query": urlencode({k: v for k, v in filters.items() if v}),
            "bulk_form": BulkTicketForm() if request.user.can("bulk_edit_tickets") else None,
        },
    )


@require_POST
@require_perm("bulk_edit_tickets")
def bulk_tickets(request):
    """Change status/severity/fault type of many tickets at once, and/or add the same comment to them all."""
    back = request.POST.get("next", "")
    if not url_has_allowed_host_and_scheme(back, {request.get_host()}) or not back.startswith("/"):
        back = reverse("open_tickets")
    form = BulkTicketForm(request.POST)
    numbers = [n for n in request.POST.getlist("tickets") if n.isdigit()]
    if not numbers:
        messages.error(request, "Tick at least one ticket first.")
        return redirect(back)
    if not form.is_valid():
        messages.error(request, " ".join(e for errs in form.errors.values() for e in errs))
        return redirect(back)
    data = {f: form.cleaned_data[f] for f in ("status", "severity", "fault_type") if form.cleaned_data.get(f)}
    comment = form.cleaned_data.get("comment", "").strip()
    saved, skipped = [], []
    for ticket in Ticket.objects.filter(number__in=numbers).order_by("number"):
        try:
            _, changed = update_ticket(ticket, request.user, data, ticket.version) if data else (ticket, [])
        except (ConflictError, PermissionDenied) as exc:
            skipped.append(f"{ticket.code} ({exc or 'someone else was saving it'})")
            continue
        if comment:
            Comment.objects.create(ticket=ticket, user=request.user, text=comment[:5000])
            Ticket.objects.filter(pk=ticket.pk).update(updated_at=timezone.now())
        if changed or comment:
            saved.append(ticket.code)
    what = [f"{Ticket.TRACKED_FIELDS[f]} → {Ticket(**{f: v}).display_value(f, v)}" for f, v in data.items()]
    if comment:
        what.append(f"comment: {comment[:200]}")
    if saved:
        record(request, "bulk", f"Bulk change to {len(saved)} tickets ({', '.join(saved)}): {'; '.join(what)}")
        messages.success(request, f"Updated {len(saved)} ticket{'s' if len(saved) != 1 else ''}.")
    else:
        messages.info(request, "Nothing changed: the ticked tickets already had those values.")
    if skipped:
        messages.warning(request, "Not changed: " + ", ".join(skipped))
    return redirect(back)


# ---------------------------------------------------------------- item types


@require_perm("view")
def item_type_list(request):
    types = ItemType.objects.annotate(
        item_count=Count("items", distinct=True),
        doc_count=Count("documents", filter=Q(documents__removed_at__isnull=True), distinct=True),
    )
    return render(request, "tracker/item_type_list.html", {"types": types})


@require_perm("manage_item_types")
def item_type_edit(request, pk=None):
    item_type = get_object_or_404(ItemType, pk=pk) if pk else None
    form = ItemTypeForm(request.POST or None, instance=item_type)
    if request.method == "POST" and form.is_valid():
        changed = form.changed_data
        saved = form.save()
        if changed or not item_type:
            record(request, "item_type", f"{'Edited' if item_type else 'Added'} item type {saved}"
                   + (f": {', '.join(changed)}" if item_type else ""))
        messages.success(request, f"Item type {saved} saved.")
        return redirect("item_type_list")
    title = f"Edit {item_type}" if item_type else "New item type"
    documents = item_type.documents.filter(removed_at__isnull=True) if item_type else []
    return render(request, "tracker/item_type_form.html", {
        "form": form, "title": title, "item_type": item_type, "documents": documents,
        "doc_form": DocumentForm() if item_type and request.user.can("manage_documents") else None,
        "doc_max_mb": _doc_max_mb(),
    })


# ---------------------------------------------------------------- documents


def _add_document(request, item_type, item, back):
    from .documents import save_document

    form = DocumentForm(request.POST, request.FILES, item=item)
    if not form.is_valid():
        messages.error(request, " ".join(e for errs in form.errors.values() for e in errs))
        return redirect(back)
    if item is not None and form.cleaned_data.get("attach_to") == "item":
        item_type = None
    else:
        item = None
    try:
        file_name, original, content_type, size = save_document(form.cleaned_data["file"])
    except ValidationError as exc:
        messages.error(request, " ".join(exc.messages))
        return redirect(back)
    title = form.cleaned_data.get("title", "").strip() or original.rsplit(".", 1)[0]
    doc = Document.objects.create(
        item_type=item_type, item=item, title=title[:200], file_name=file_name, original_name=original,
        content_type=content_type, size=size, uploaded_by=request.user,
    )
    record(request, "document", f"Added document “{doc.title}” to {doc.owner_label}", back)
    messages.success(request, f"Added “{doc.title}”.")
    return redirect(back)


@require_POST
@require_perm("manage_documents")
def document_add_item(request, pk):
    item = get_object_or_404(Item.objects.select_related("item_type"), pk=pk)
    return _add_document(request, item.item_type, item, reverse("item_detail", args=[item.pk]) + "#documents")


@require_POST
@require_perm("manage_documents")
def document_add_type(request, pk):
    item_type = get_object_or_404(ItemType, pk=pk)
    return _add_document(request, item_type, None, reverse("item_type_edit", args=[item_type.pk]) + "#documents")


@require_perm("view")
def document_open(request, pk):
    from django.conf import settings

    doc = get_object_or_404(Document, pk=pk, removed_at__isnull=True)
    path = settings.DOCUMENTS_DIR / doc.file_name
    if not path.is_file():
        raise Http404
    from .documents import INLINE

    response = FileResponse(open(path, "rb"), content_type=doc.content_type,
                            as_attachment=doc.content_type not in INLINE, filename=doc.original_name)
    response["X-Content-Type-Options"] = "nosniff"
    response["Content-Security-Policy"] = "sandbox"  # an uploaded file can't run scripts in the app
    response["Cache-Control"] = "private, max-age=3600"
    return response


@require_POST
@require_perm("manage_documents")
def document_remove(request, pk):
    doc = get_object_or_404(Document.objects.select_related("item", "item_type"), pk=pk)
    back = request.POST.get("next", "")
    if not back.startswith("/") or not url_has_allowed_host_and_scheme(back, {request.get_host()}):
        back = reverse("item_detail", args=[doc.item_id]) if doc.item_id else reverse("item_type_edit", args=[doc.item_type_id])
    if not doc.removed_at:
        Document.objects.filter(pk=doc.pk).update(removed_at=timezone.now(), removed_by=request.user)
        record(request, "document", f"Removed document “{doc.title}” from {doc.owner_label} (file kept)", back)
        messages.success(request, f"Removed “{doc.title}”. The file is kept and the removal is logged.")
    return redirect(back)


@require_POST
@require_perm("delete_records")
def document_delete(request, pk):
    doc = get_object_or_404(Document.objects.select_related("item", "item_type"), pk=pk)
    _require_permanent_delete(request)
    back = request.POST.get("next", "")
    if not back.startswith("/") or not url_has_allowed_host_and_scheme(back, {request.get_host()}):
        back = reverse("item_detail", args=[doc.item_id]) if doc.item_id else reverse("item_type_edit", args=[doc.item_type_id])
    title, owner = doc.title, doc.owner_label
    deletion.delete_document(doc)
    record(request, "deletion", f"Permanently deleted document “{title}” from {owner}", back)
    messages.success(request, f"“{title}” permanently deleted.")
    return redirect(back)


# ---------------------------------------------------------------- reports


@require_perm("export")
def reports(request):
    from django.http import HttpResponse

    from .reports import (
        ReportForm,
        build_pdf,
        build_xlsx,
        describe_filters,
        filter_tickets,
    )

    submitted = "action" in request.GET
    form = ReportForm(request.GET if submitted else None)
    ctx = {"form": form, "submitted": submitted}
    if submitted and form.is_valid():
        data = form.cleaned_data
        tickets = filter_tickets(data)
        action = request.GET.get("action")
        stamp = timezone.localtime().strftime("%Y-%m-%d_%H%M")
        if action == "blank_labels":
            from .labels import build_labels_pdf

            colour = data.get("template_colour") or "none"
            pdf = build_labels_pdf([], fill_templates=True, template_severity=colour,
                                   start_at=data.get("label_start") or 1, outlines=data.get("label_outlines"))
            record(request, "export", f"Downloaded a sheet of write-in labels ({colour})")
            response = HttpResponse(pdf, content_type="application/pdf")
            response["Content-Disposition"] = f'attachment; filename="write-in-labels_{stamp}.pdf"'
            return response
        if action in ("xlsx", "pdf", "labels"):
            kind = {"xlsx": "spreadsheet", "pdf": "PDF report", "labels": "sticker sheet"}[action]
            record(request, "export", f"Downloaded a {kind} of {tickets.count()} tickets ("
                   + "; ".join(f"{label}: {value}" for label, value in describe_filters(data)) + ")")
        if action == "xlsx":
            response = HttpResponse(
                build_xlsx(tickets, data),
                content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
            response["Content-Disposition"] = f'attachment; filename="tickets_{stamp}.xlsx"'
            return response
        if action == "labels":
            from .labels import build_labels_pdf

            pdf = build_labels_pdf(
                tickets.select_related("item"),
                fill_templates=data.get("fill_templates"),
                template_severity=data.get("template_colour") or "none",
                start_at=data.get("label_start") or 1,
                outlines=data.get("label_outlines"),
            )
            response = HttpResponse(pdf, content_type="application/pdf")
            response["Content-Disposition"] = f'attachment; filename="labels_{stamp}.pdf"'
            return response
        if action == "pdf":
            response = HttpResponse(build_pdf(tickets, data), content_type="application/pdf")
            response["Content-Disposition"] = f'attachment; filename="tickets_{stamp}.pdf"'
            return response
        ctx.update({
            "results": True,
            "count": tickets.count(),
            "total_cost": tickets.aggregate(s=Sum("repair_cost"))["s"],
            "total_hours": tickets.aggregate(s=Sum("repair_time"))["s"],
            "bulk_form": BulkTicketForm() if request.user.can("bulk_edit_tickets") else None,
            "tickets": tickets[:200],
            "filters": describe_filters(data),
            "query": request.GET.urlencode(),
        })
    return render(request, "tracker/reports.html", ctx)


@login_not_required
def health(request):
    """Used by the Windows scripts: proves the app can open and write its database."""
    from django.db import connection, transaction
    from django.http import HttpResponse

    try:
        # A real write (rolled back), so a read-only or locked database is caught too.
        with transaction.atomic():
            with connection.cursor() as cur:
                cur.execute(
                    "UPDATE django_migrations SET app = app WHERE id = (SELECT MIN(id) FROM django_migrations)"
                )
            transaction.set_rollback(True)
    except Exception as exc:
        return HttpResponse(f"database error: {exc}", status=503, content_type="text/plain")
    return HttpResponse("ok", content_type="text/plain")
