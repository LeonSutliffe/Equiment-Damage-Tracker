from django.conf import settings
from django.db import models
from django.utils import timezone


class ItemType(models.Model):
    """A kind of item shared by many units, e.g. "Step ladder 3m"."""

    name = models.CharField(max_length=150, unique=True)
    description = models.CharField(max_length=255, blank=True)
    active = models.BooleanField(default=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class Item(models.Model):
    """One physical unit, identified by both a barcode and a serial number."""

    item_type = models.ForeignKey(ItemType, on_delete=models.PROTECT, related_name="items")
    barcode = models.CharField(max_length=100, unique=True)
    serial_number = models.CharField(max_length=100, unique=True)
    notes = models.TextField(blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")
    created_at = models.DateTimeField(default=timezone.now)
    active = models.BooleanField(default=True)

    TRACKED_FIELDS = {"item_type": "Item type", "barcode": "Barcode", "serial_number": "Serial number", "notes": "Notes"}

    class Meta:
        ordering = ["item_type__name", "serial_number"]

    def __str__(self):
        return f"{self.item_type} ({self.serial_number})"


class ItemChange(models.Model):
    item = models.ForeignKey(Item, on_delete=models.CASCADE, related_name="changes")
    field = models.CharField(max_length=50)
    old_value = models.TextField(blank=True)
    new_value = models.TextField(blank=True)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")
    changed_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["-changed_at", "-id"]


class Ticket(models.Model):
    class Status(models.TextChoices):
        OPEN = "open", "Open"
        IN_PROGRESS = "in_progress", "Repair in Progress"
        RESOLVED = "resolved", "Resolved"

    class FaultType(models.TextChoices):
        COSMETIC = "cosmetic", "Cosmetic"
        FUNCTIONALITY = "functionality", "Functionality"
        SAFETY = "safety", "Safety"

    class Severity(models.TextChoices):
        LOW = "low", "Low"
        MEDIUM = "medium", "Medium"
        HIGH = "high", "High"

    number = models.PositiveIntegerField(unique=True, editable=False)
    item = models.ForeignKey(Item, on_delete=models.PROTECT, related_name="tickets")
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.OPEN)
    fault_type = models.CharField(max_length=20, choices=FaultType.choices)
    severity = models.CharField(max_length=10, choices=Severity.choices)
    fault_description = models.TextField(blank=True)
    work_done = models.TextField(blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(default=timezone.now)
    # Goes up by one on every save; used to spot two people editing at once.
    version = models.PositiveIntegerField(default=1)

    # Fields whose changes are recorded in FieldChange, in screen order.
    TRACKED_FIELDS = {
        "status": "Status",
        "fault_type": "Fault Type",
        "severity": "Severity",
        "fault_description": "Fault Description",
        "photos": "Photos",
        "work_done": "Work Done",
    }

    class Meta:
        ordering = ["-number"]

    def __str__(self):
        return self.code

    @property
    def code(self):
        return f"T-{self.number:05d}"

    @property
    def is_resolved(self):
        return self.status == self.Status.RESOLVED

    def display_value(self, field, raw):
        """Turn a stored value (e.g. "in_progress") into what the screen shows."""
        choices = {
            "status": self.Status,
            "fault_type": self.FaultType,
            "severity": self.Severity,
        }.get(field)
        if choices and raw:
            try:
                return choices(raw).label
            except ValueError:
                return raw
        return raw


class Photo(models.Model):
    ticket = models.ForeignKey(Ticket, on_delete=models.PROTECT, related_name="photos")
    file_name = models.CharField(max_length=100)
    thumbnail_file_name = models.CharField(max_length=100)
    original_name = models.CharField(max_length=255, blank=True)
    content_type = models.CharField(max_length=50, default="image/jpeg")
    size = models.PositiveIntegerField(default=0)
    uploaded_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")
    uploaded_at = models.DateTimeField(default=timezone.now)
    removed_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    removed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["uploaded_at", "id"]

    def __str__(self):
        return f"Photo {self.pk} on {self.ticket}"

    @property
    def label(self):
        return f"Photo {self.pk}" + (f" ({self.original_name})" if self.original_name else "")


class FieldChange(models.Model):
    """One row per changed field per save; drives the long-press history popup."""

    ticket = models.ForeignKey(Ticket, on_delete=models.CASCADE, related_name="changes")
    field = models.CharField(max_length=50)
    old_value = models.TextField(blank=True)
    new_value = models.TextField(blank=True)
    note = models.CharField(max_length=50, blank=True)  # "created", "added", "removed"
    photo = models.ForeignKey(Photo, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")
    changed_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["-changed_at", "-id"]
        indexes = [models.Index(fields=["ticket", "field"])]


class Comment(models.Model):
    """A note on a ticket. Comments can't be edited or deleted, so the conversation stays as written."""

    ticket = models.ForeignKey(Ticket, on_delete=models.CASCADE, related_name="comments")
    text = models.TextField()
    user = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["created_at", "id"]
