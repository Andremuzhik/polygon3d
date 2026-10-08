from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import UserCreationForm

from .models import Order, OrderMessage, Service

User = get_user_model()


class OrderForm(forms.ModelForm):
    # Honeypot: людям поле не видно, боты его заполняют.
    website = forms.CharField(required=False, widget=forms.TextInput(attrs={"tabindex": "-1"}))

    class Meta:
        model = Order
        fields = [
            "service",
            "name",
            "email",
            "phone",
            "telegram_username",
            "budget",
            "deadline",
            "description",
            "reference_file",
        ]
        widgets = {
            "deadline": forms.DateInput(attrs={"type": "date"}),
            "description": forms.Textarea(attrs={"rows": 6}),
            "telegram_username": forms.TextInput(attrs={"placeholder": "@username"}),
            "phone": forms.TextInput(attrs={"placeholder": "+7 900 000-00-00"}),
            "budget": forms.TextInput(attrs={"placeholder": "например, 15 000 ₽"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["service"].queryset = Service.objects.filter(is_active=True)
        self.fields["service"].empty_label = "Пока не определился"
        self.fields["description"].help_text = "Что нужно сделать, для чего, в каком стиле."
        self.fields[
            "reference_file"
        ].help_text = "jpg, png, pdf, zip, obj, fbx, stl, glb — до 20 МБ"

    def clean_website(self):
        if self.cleaned_data["website"]:
            raise forms.ValidationError("Похоже на спам.")
        return ""

    def clean_telegram_username(self):
        return self.cleaned_data["telegram_username"].lstrip("@").strip()

    def clean(self):
        cleaned = super().clean()
        if not any(cleaned.get(f) for f in ("email", "phone", "telegram_username")):
            raise forms.ValidationError(
                "Укажите хотя бы один способ связи: email, телефон или Telegram."
            )
        return cleaned


class MessageForm(forms.ModelForm):
    class Meta:
        model = OrderMessage
        fields = ["text"]
        widgets = {"text": forms.Textarea(attrs={"rows": 3, "placeholder": "Напишите менеджеру…"})}
        labels = {"text": ""}


class RegisterForm(UserCreationForm):
    email = forms.EmailField(label="Email")

    class Meta(UserCreationForm.Meta):
        model = User
        fields = ("username", "email")

    def clean_email(self):
        email = self.cleaned_data["email"].lower()
        if User.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError("Пользователь с таким email уже есть.")
        return email


class RevisionForm(forms.Form):
    text = forms.CharField(
        label="",
        max_length=2000,
        widget=forms.Textarea(
            attrs={
                "rows": 3,
                "placeholder": "Что нужно изменить? Опишите правки как можно конкретнее.",
            }
        ),
    )
