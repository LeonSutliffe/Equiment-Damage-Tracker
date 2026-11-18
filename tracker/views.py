from django.contrib import messages
from django.contrib.auth.decorators import login_not_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.db.models import Case, Count, IntegerField, Q, Value, When
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.http import urlencode
from django.views.decorators.http import require_POST

from accounts.permissions import require_perm

from .forms import ItemForm, ItemTypeForm, TicketForm
from .models import Comment, FieldChange, Item, ItemChange, ItemType, Photo, Ticket
from .search import search
from .services import ConflictError, create_item, create_ticket, remove_photo, update_item, update_ticket

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
    page = Paginator(items, 50).get_page(request.GET.get("page"))
    return render(
        request,
        "tracker/item_list.html",
        {"page": page, "item_types": ItemType.objects.all(), "type_id": type_id or ""},
    )


@require_perm("view")
def item_detail(request, pk):
    item = get_object_or_404(Item.objects.select_related("item_type"), pk=pk)
    tickets = item.tickets.all().order_by("-created_at")
    return render(request, "tracker/item_detail.html", {"item": item, "tickets": tickets})


@require_perm("create_item")
def item_create(request):
    initial = {k: request.GET[k] for k in ("barcode", "serial_number") if request.GET.get(k)}
    form = ItemForm(request.POST or None, initial=initial)
    if request.method == "POST" and form.is_valid():
        item = create_item(request.user, form.cleaned_data)
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
        update_item(form.instance, request.user, form.cleaned_data)
        messages.success(request, "Item saved.")
        return redirect("item_detail", pk=item.pk)
    return render(request, "tracker/item_form.html", {"form": form, "title": f"Edit {item}", "item": item})


@require_perm("view")
def item_history(request, pk, field):
    item = get_object_or_404(Item, pk=pk)
    if field not in Item.TRACKED_FIELDS:
        raise Http404
    changes = ItemChange.objects.filter(item=item, field=field).select_related("user")
    return render(
        request,
        "tracker/history_popup.html",
        {"label": Item.TRACKED_FIELDS[field], "field": field, "entries": [_entry(c, c.old_value, c.new_value) for c in changes]},
    )


# ---------------------------------------------------------------- tickets


@require_perm("create_ticket")
def ticket_create(request, item_pk):
    item = get_object_or_404(Item.objects.select_related("item_type"), pk=item_pk)
    form = TicketForm(request.POST or None, request.FILES or None, creating=True)
    if request.method == "POST" and form.is_valid():
        try:
            ticket = create_ticket(item, request.user, form.cleaned_data, form.cleaned_data.get("photos", []))
        except ValidationError as exc:
            form.add_error("photos", exc)
        else:
            messages.success(request, f"Ticket {ticket.code} created.")
            return redirect("ticket_detail", number=ticket.number)
    return render(request, "tracker/ticket.html", {"form": form, "item": item, "ticket": None, "can_edit": True})


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
            data = {f: form.cleaned_data[f] for f in ("status", "fault_type", "severity", "fault_description", "work_done")}
            try:
                ticket, changed = update_ticket(
                    ticket, request.user, data, form.cleaned_data.get("version") or 0, form.cleaned_data.get("photos", [])
                )
            except ConflictError:
                # Someone else saved first: show the latest version and what this user typed.
                conflict = {
                    Ticket.TRACKED_FIELDS[f]: ticket.display_value(f, v) for f, v in data.items() if v
                }
                ticket.refresh_from_db()
            except ValidationError as exc:
                form.add_error("photos", exc)
            else:
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
    comments = ticket.comments.select_related("user")
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
        messages.success(request, "Comment added.")
    return redirect(reverse("ticket_detail", args=[ticket.number]) + "#comments")


def _entry(change, old, new):
    return {"when": change.changed_at, "who": change.user.label if change.user else "(deleted user)",
            "old": old, "new": new, "note": change.note}


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
    remove_photo(photo, request.user)
    messages.success(request, "Photo removed from the ticket. It is kept and the removal is logged.")
    return redirect("ticket_detail", number=photo.ticket.number)


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
        },
    )


# ---------------------------------------------------------------- item types


@require_perm("view")
def item_type_list(request):
    types = ItemType.objects.annotate(item_count=Count("items"))
    return render(request, "tracker/item_type_list.html", {"types": types})


@require_perm("manage_item_types")
def item_type_edit(request, pk=None):
    item_type = get_object_or_404(ItemType, pk=pk) if pk else None
    form = ItemTypeForm(request.POST or None, instance=item_type)
    if request.method == "POST" and form.is_valid():
        saved = form.save()
        messages.success(request, f"Item type {saved} saved.")
        return redirect("item_type_list")
    title = f"Edit {item_type}" if item_type else "New item type"
    return render(request, "tracker/item_type_form.html", {"form": form, "title": title})


# ---------------------------------------------------------------- reports


@require_perm("export")
def reports(request):
    from django.http import HttpResponse

    from .reports import ReportForm, build_pdf, build_xlsx, describe_filters, filter_tickets

    submitted = "action" in request.GET
    form = ReportForm(request.GET if submitted else None)
    ctx = {"form": form, "submitted": submitted}
    if submitted and form.is_valid():
        data = form.cleaned_data
        tickets = filter_tickets(data)
        action = request.GET.get("action")
        stamp = timezone.localtime().strftime("%Y-%m-%d_%H%M")
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
    except Exception as exc:  # noqa: BLE001 - report any database problem
        return HttpResponse(f"database error: {exc}", status=503, content_type="text/plain")
    return HttpResponse("ok", content_type="text/plain")
