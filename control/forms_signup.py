from django import forms
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError


class SignupRequestForm(forms.Form):
    email = forms.EmailField(max_length=254)
    password = forms.CharField(strip=False, widget=forms.PasswordInput)
    password_confirm = forms.CharField(strip=False, widget=forms.PasswordInput)
    name_display = forms.CharField(max_length=200)
    organization_name = forms.CharField(max_length=200)
    signup_purpose = forms.CharField(max_length=1000, widget=forms.Textarea)
    terms_agreed = forms.BooleanField(required=True)
    privacy_agreed = forms.BooleanField(required=True)

    def clean_email(self):
        return self.cleaned_data["email"].strip().lower()

    def clean(self):
        cleaned = super().clean()
        password = cleaned.get("password")
        confirmation = cleaned.get("password_confirm")

        if password and confirmation and password != confirmation:
            self.add_error("password_confirm", "비밀번호가 일치하지 않습니다.")

        if password:
            try:
                validate_password(password)
            except ValidationError as exc:
                self.add_error("password", exc)

        return cleaned


class SignupVerificationResendForm(forms.Form):
    email = forms.EmailField(max_length=254)

    def clean_email(self):
        return self.cleaned_data["email"].strip().lower()
