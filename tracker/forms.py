from django import forms
from django.core.exceptions import ValidationError

from .models import Item, ItemType, Ticket


class MultipleFileInput(forms.ClearableFileInput):
    allow_multiple_selected = True


class MultiplePhotoField(forms.FileField):
    def __init__(self, *args, **kwargs):
        kwargs.setdefault("widget", MultipleFileInput(attrs={"accept": "image/*", "multiple": True}))
        kwargs.setdefault("required", False)
        super().__init__(*args, **kwargs)

    def clean(self, data, initial=None):
        if not data:
            return []
        files = data if isinstance(data, (list, tuple)) else [data]
        return [super(MultiplePhotoField, self).clean(f, initial) for f in files]


class SegmentedRadio(forms.RadioSelect):
    template_name = "tracker/widgets/segmented.html"
    option_template_name = "django/forms/widgets/radio_option.html"


class ItemForm(forms.ModelForm):
    class Meta:
        model = Item
        fields = ["item_type", "barcode", "serial_number", "notes"]
        widgets = {
            "barcode": forms.TextInput(attrs={"autocomplete": "off", "autocapitalize": "none"}),
            "serial_number": forms.TextInput(attrs={"autocomplete": "off", "autocapitalize": "characters"}),
            "notes": forms.Textarea(attrs={"rows": 2}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        types = ItemType.objects.filter(active=True)
        if self.instance.pk:
            types = ItemType.objects.filter(active=True) | ItemType.objects.filter(pk=self.instance.item_type_id)
        self.fields["item_type"].queryset = types.distinct()
        self.fields["item_type"].empty_label = "Choose item type…"

    def _clean_unique(self, field, label):
        value = self.cleaned_data[field].strip()
        other = Item.objects.filter(**{f"{field}__iexact": value}).exclude(pk=self.instance.pk).first()
        if other:
            raise ValidationError(f"{label} {value} is already used by {other}.")
        return value

    def clean_barcode(self):
        return self._clean_unique("barcode", "Barcode")

    def clean_serial_number(self):
        return self._clean_unique("serial_number", "Serial number")


class TicketForm(forms.ModelForm):
    photos = MultiplePhotoField(label="Add photos")
    version = forms.IntegerField(widget=forms.HiddenInput, required=False)

    class Meta:
        model = Ticket
        fields = ["status", "fault_type", "severity", "fault_description", "work_done", "repair_cost"]
        widgets = {
            "repair_cost": forms.NumberInput(attrs={"step": "0.01", "min": "0", "inputmode": "decimal", "placeholder": "0.00"}),
            "status": SegmentedRadio,
            "fault_type": SegmentedRadio,
            "severity": SegmentedRadio,
            "fault_description": forms.Textarea(attrs={"rows": 3}),
            "work_done": forms.Textarea(attrs={"rows": 3}),
        }
        labels = {"fault_type": "Fault Type", "fault_description": "Fault Description", "work_done": "Work Done",
                  "repair_cost": "Repair Cost (£)"}

    def __init__(self, *args, creating=False, **kwargs):
        super().__init__(*args, **kwargs)
        for name in ("status", "fault_type", "severity"):
            self.fields[name].choices = [c for c in self.fields[name].choices if c[0]]
        if creating:
            del self.fields["status"]  # a new ticket always starts as Open
            del self.fields["version"]


class ItemTypeForm(forms.ModelForm):
    class Meta:
        model = ItemType
        fields = ["name", "description", "active"]

    def clean_name(self):
        name = self.cleaned_data["name"].strip()
        if ItemType.objects.filter(name__iexact=name).exclude(pk=self.instance.pk).exists():
            raise ValidationError("An item type with that name already exists.")
        return name


class WriteOffForm(forms.Form):
    reason = forms.CharField(
        label="Reason", max_length=1000,
        widget=forms.Textarea(attrs={"rows": 3, "placeholder": "e.g. Beyond economic repair, scrapped 18 Nov"}),
    )


class BulkTicketForm(forms.Form):
    status = forms.ChoiceField(required=False, label="Set status",
                               choices=[("", "Ignore status")] + list(Ticket.Status.choices))
    severity = forms.ChoiceField(required=False, label="Set severity",
                                 choices=[("", "Ignore severity")] + list(Ticket.Severity.choices))
    fault_type = forms.ChoiceField(required=False, label="Set fault type",
                                   choices=[("", "Ignore fault type")] + list(Ticket.FaultType.choices))
    comment = forms.CharField(required=False, label="Add a comment to each", max_length=5000,
                              widget=forms.TextInput(attrs={"placeholder": "Comment for each (optional)"}))

    def clean(self):
        data = super().clean()
        if not any(data.get(f) for f in ("status", "severity", "fault_type")) and not data.get("comment", "").strip():
            raise ValidationError("Choose something to change, or type a comment.")
        return data
