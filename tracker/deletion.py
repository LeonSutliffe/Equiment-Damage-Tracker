"""Removing and permanently deleting records (admins with the Delete records permission).

- Visible removal (the normal mode): a comment is hidden and a "removed by ... on ..."
  note stays in its place and in the item history.
- Permanent deletion (only when the admin has switched on "Allow permanent deletions"
  in their Settings): the database rows are erased, so nothing shows in the ticket or
  item history. The audit log still records who deleted what.

Photo and document files live in the delete-protected data folder. The app is not
allowed to delete files there (that protection is deliberate), so a permanently deleted
file is emptied instead: its contents are erased and only a 0-byte placeholder with a
random name remains.
"""

import logging

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from .models import Comment, Document, FieldChange, Item, Photo, Ticket

log = logging.getLogger(__name__)


def can_delete_permanently(user):
    return user.can("delete_records") and user.allow_permanent_delete


def erase_file(path):
    """Delete a file if Windows allows it, otherwise empty it. Never raises."""
    try:
        if path.is_file():
            try:
                path.unlink()
            except PermissionError:
                with open(path, "r+b") as f:
                    f.truncate(0)
    except OSError:
        log.exception("Couldn't erase %s", path)


def _photo_files(photos):
    out = []
    for p in photos:
        out += [settings.PHOTOS_DIR / p.file_name, settings.PHOTOS_DIR / p.thumbnail_file_name]
    return out


def remove_comment(comment, user):
    """Visible removal: hide the text, keep a note."""
    if not comment.removed_at:
        Comment.objects.filter(pk=comment.pk).update(removed_at=timezone.now(), removed_by=user)


def delete_comment(comment):
    comment.delete()  # its edit history goes with it


def delete_photo(photo):
    files = _photo_files([photo])
    with transaction.atomic():
        FieldChange.objects.filter(photo=photo).delete()  # no trace in the Photos history
        photo.delete()
    for f in files:
        erase_file(f)


def delete_document(doc):
    path = settings.DOCUMENTS_DIR / doc.file_name
    doc.delete()
    erase_file(path)


def ticket_summary(ticket):
    return {
        "photos": ticket.photos.count(),
        "comments": ticket.comments.count(),
        "changes": ticket.changes.count(),
    }


def delete_ticket(ticket):
    """Erase a ticket with its photos, comments and field history."""
    photos = list(Photo.objects.filter(ticket=ticket))
    files = _photo_files(photos)
    with transaction.atomic():
        ticket.changes.all().delete()
        Photo.objects.filter(ticket=ticket).delete()
        ticket.delete()  # comments and their edits cascade
    for f in files:
        erase_file(f)


def item_summary(item):
    tickets = Ticket.objects.filter(item=item)
    return {
        "tickets": tickets.count(),
        "photos": Photo.objects.filter(ticket__in=tickets).count(),
        "documents": Document.objects.filter(item=item).count(),
    }


def delete_item(item):
    """Erase an item with all its tickets, photos, item-only documents and history."""
    docs = list(Document.objects.filter(item=item))
    for t in list(Ticket.objects.filter(item=item)):
        delete_ticket(t)
    with transaction.atomic():
        Document.objects.filter(item=item).delete()
        Item.objects.filter(pk=item.pk).delete()  # item history cascades
    for d in docs:
        erase_file(settings.DOCUMENTS_DIR / d.file_name)
