from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models
from django.utils import timezone


def format_cost(value):
    """12.5 -> "£12.50"; blank stays blank."""
    if value in ("", None):
        return ""
    try:
        from decimal import Decimal

        return f"£{Decimal(str(value)):,.2f}"
    except Exception:
        return str(value)


def format_hours(value):
    """2.5 -> "2.5 h"; blank stays blank."""
    if value in ("", None):
        return ""
    try:
        from decimal import Decimal

        text = f"{Decimal(str(value)):.2f}".rstrip("0").rstrip(".")
        return f"{text} h"
    except Exception:  # noqa: BLE001
        return str(value)


class ItemType(models.Model):
    """A kind of item shared by many units: manufacturer + model, e.g. "Zarges Step ladder 3m"."""

    manufacturer = models.CharField(max_length=150, blank=True)
    name = models.CharField("model name", max_length=150)  # shown as "Model name"
    description = models.CharField(max_length=255, blank=True)
    active = models.BooleanField(default=True)

    class Meta:
        ordering = ["manufacturer", "name"]
        constraints = [
            models.UniqueConstraint(fields=["manufacturer", "name"], name="item_type_unique_manufacturer_model"),
        ]

    def __str__(self):
        return f"{self.manufacturer} {self.name}" if self.manufacturer else self.name


class Item(models.Model):
    """One physical unit, identified by both a barcode and a serial number."""

    item_type = models.ForeignKey(ItemType, on_delete=models.PROTECT, related_name="items")
    barcode = models.CharField(max_length=100, unique=True)
    serial_number = models.CharField(max_length=100, unique=True)
    notes = models.TextField(blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")
    created_at = models.DateTimeField(default=timezone.now)
    active = models.BooleanField(default=True)
    # Write-off / disposal: the item and its history are kept, but no new tickets can be logged.
    written_off_at = models.DateTimeField(null=True, blank=True)
    written_off_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    write_off_reason = models.TextField(blank=True)

    TRACKED_FIELDS = {"item_type": "Item type", "barcode": "Barcode", "serial_number": "Serial number", "notes": "Notes"}
    # Fields with a history popup: the editable ones plus write-off/reinstate.
    HISTORY_FIELDS = {**TRACKED_FIELDS, "write_off": "Write-off"}

    class Meta:
        ordering = ["item_type__manufacturer", "item_type__name", "serial_number"]

    def __str__(self):
        return f"{self.item_type} ({self.serial_number})"

    @property
    def is_written_off(self):
        return self.written_off_at is not None


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
    previous_job = models.CharField(max_length=200, blank=True)  # job/event the item was last used on
    work_done = models.TextField(blank=True)
    repair_cost = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True, validators=[MinValueValidator(0)]
    )
    repair_time = models.DecimalField(  # hours spent on the repair
        max_digits=7, decimal_places=2, null=True, blank=True, validators=[MinValueValidator(0)]
    )
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
        "previous_job": "Previous Job",
        "fault_description": "Fault Description",
        "photos": "Photos",
        "work_done": "Work Done",
        "repair_cost": "Repair Cost",
        "repair_time": "Repair Time",
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
        if field == "repair_cost" and raw not in ("", None):
            return format_cost(raw)
        if field == "repair_time" and raw not in ("", None):
            return format_hours(raw)
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


class Document(models.Model):
    """A manual, spec sheet, certificate or other file.

    Attached either to an item type (shown on every item of that type) or to one item.
    Removing it only hides it; the file is kept and the removal is logged.
    """

    item_type = models.ForeignKey(ItemType, null=True, blank=True, on_delete=models.PROTECT, related_name="documents")
    item = models.ForeignKey(Item, null=True, blank=True, on_delete=models.PROTECT, related_name="documents")
    title = models.CharField(max_length=200)
    file_name = models.CharField(max_length=100)
    original_name = models.CharField(max_length=255)
    content_type = models.CharField(max_length=100)
    size = models.PositiveBigIntegerField(default=0)
    uploaded_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")
    uploaded_at = models.DateTimeField(default=timezone.now)
    removed_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    removed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["title", "id"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(item_type__isnull=False, item__isnull=True)
                | models.Q(item_type__isnull=True, item__isnull=False),
                name="document_belongs_to_type_or_item",
            )
        ]

    def __str__(self):
        return self.title

    @property
    def extension(self):
        return self.original_name.rsplit(".", 1)[-1].upper() if "." in self.original_name else ""

    @property
    def owner_label(self):
        return f"all {self.item_type}" if self.item_type_id else str(self.item)


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
