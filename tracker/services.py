"""Business rules for items and tickets.

Every change to a ticket field writes FieldChange rows in the same database
transaction as the save, so the history can never be missing or out of step
(architecture section 6).
"""

from django.core.exceptions import PermissionDenied
from django.db import IntegrityError, transaction
from django.db.models import Max
from django.utils import timezone

from .models import FieldChange, Item, ItemChange, Photo, Ticket
from .photos import process_upload

TEXT_FIELDS = ("status", "fault_type", "severity", "fault_description", "work_done")


class ConflictError(Exception):
    """Someone else saved the ticket after this user opened it."""


def _next_number():
    return (Ticket.objects.aggregate(m=Max("number"))["m"] or 0) + 1


def check_status_change(user, old_status, new_status):
    """Resolve and reopen need their own permissions (architecture section 4)."""
    if old_status == new_status:
        return
    if new_status == Ticket.Status.RESOLVED and not user.can("resolve_ticket"):
        raise PermissionDenied("Your role can't resolve tickets.")
    if old_status == Ticket.Status.RESOLVED and not user.can("reopen_ticket"):
        raise PermissionDenied("Your role can't reopen resolved tickets.")


def prepare_photos(files):
    """Validate and store uploaded files before touching the database.

    Raises ValidationError on the first bad file, so nothing is saved.
    """
    prepared = []
    for f in files:
        file_name, thumb_name, size = process_upload(f)
        prepared.append((file_name, thumb_name, size, f.name[:255]))
    return prepared


def _save_photos(ticket, user, prepared, now):
    added = []
    for file_name, thumb_name, size, original_name in prepared:
        photo = Photo.objects.create(
            ticket=ticket, file_name=file_name, thumbnail_file_name=thumb_name,
            original_name=original_name, size=size, uploaded_by=user, uploaded_at=now,
        )
        FieldChange.objects.create(
            ticket=ticket, field="photos", note="added", new_value=photo.label,
            photo=photo, user=user, changed_at=now,
        )
        added.append(photo)
    return added


def create_ticket(item, user, data, photos=()):
    """Create a ticket; writes a "created" history row for every filled-in field."""
    check_status_change(user, Ticket.Status.OPEN, data.get("status", Ticket.Status.OPEN))
    photos = prepare_photos(photos)
    for attempt in range(5):
        try:
            with transaction.atomic():
                now = timezone.now()
                ticket = Ticket.objects.create(
                    number=_next_number(), item=item, created_by=user, created_at=now, updated_at=now,
                    **{f: data.get(f, "") or "" for f in TEXT_FIELDS if f != "status"},
                    status=data.get("status") or Ticket.Status.OPEN,
                )
                for field in TEXT_FIELDS:
                    value = getattr(ticket, field)
                    if value:
                        FieldChange.objects.create(
                            ticket=ticket, field=field, new_value=value, note="created", user=user, changed_at=now
                        )
                _save_photos(ticket, user, photos, now)
                return ticket
        except IntegrityError:
            # Two tickets got the same number at the same moment; try the next one.
            if attempt == 4:
                raise


def update_ticket(ticket, user, data, expected_version, photos=()):
    """Save changed fields, log each one, and add any new photos.

    Raises ConflictError if the ticket was saved by someone else since
    `expected_version` was read.
    """
    photos = prepare_photos(photos)
    with transaction.atomic():
        current = Ticket.objects.get(pk=ticket.pk)
        if current.version != expected_version:
            raise ConflictError
        check_status_change(user, current.status, data.get("status", current.status))
        now = timezone.now()
        changed = []
        for field in TEXT_FIELDS:
            if field not in data:
                continue
            old, new = getattr(current, field), data[field] or ""
            if old != new:
                changed.append(field)
                setattr(current, field, new)
                FieldChange.objects.create(
                    ticket=current, field=field, old_value=old, new_value=new, user=user, changed_at=now
                )
        added = _save_photos(current, user, photos, now)
        if not changed and not added:
            return current, False
        # Bump the version only if nobody else did in the meantime.
        bumped = Ticket.objects.filter(pk=current.pk, version=expected_version).update(
            version=expected_version + 1, updated_at=now, **{f: getattr(current, f) for f in changed}
        )
        if not bumped:
            raise ConflictError
        current.version = expected_version + 1
        current.updated_at = now
        return current, True


def remove_photo(photo, user):
    """Hide a photo. The file is kept and the removal is logged."""
    if photo.removed_at:
        return
    with transaction.atomic():
        now = timezone.now()
        photo.removed_by, photo.removed_at = user, now
        photo.save(update_fields=["removed_by", "removed_at"])
        FieldChange.objects.create(
            ticket=photo.ticket, field="photos", note="removed", old_value=photo.label,
            photo=photo, user=user, changed_at=now,
        )
        Ticket.objects.filter(pk=photo.ticket_id).update(updated_at=now)


def _item_value(item, field):
    value = getattr(item, field)
    return str(value) if value is not None else ""


def update_item(item, user, cleaned):
    """Save item edits and log each changed field in ItemChange."""
    with transaction.atomic():
        before = Item.objects.get(pk=item.pk)
        now = timezone.now()
        for field in Item.TRACKED_FIELDS:
            old, new = _item_value(before, field), _item_value(item, field)
            if old != new:
                ItemChange.objects.create(item=item, field=field, old_value=old, new_value=new, user=user, changed_at=now)
        item.save()


def create_item(user, cleaned):
    with transaction.atomic():
        item = Item.objects.create(created_by=user, **cleaned)
        now = item.created_at
        for field in Item.TRACKED_FIELDS:
            value = _item_value(item, field)
            if value:
                ItemChange.objects.create(item=item, field=field, new_value=value, user=user, changed_at=now)
        return item
