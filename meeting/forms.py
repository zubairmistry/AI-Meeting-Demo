from django import forms
from .models import AISettings
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.forms import AuthenticationForm
from django.contrib.auth.models import User
from django.contrib.auth import authenticate

from django.core.exceptions import ValidationError


class AISettingsForm(forms.ModelForm):
    api_key = forms.CharField(
        widget=forms.PasswordInput(
            attrs={
                "class": "form-control",
                "placeholder": "Enter API Key"
            },
            render_value=False
        ),
        required=False
    )

    class Meta:
        model = AISettings
        fields = [
            "provider",
            "api_key",
            "model_name"
        ]

        widgets = {
            "provider": forms.Select(
                attrs={
                    "class": "form-select"
                }
            ),

            "model_name": forms.TextInput(
                attrs={
                    "class": "form-control",
                    "placeholder": "gemini-2.5-flash"
                }
            ),
        }

class RegisterForm(UserCreationForm):

    def clean_email(self):

        email = self.cleaned_data.get("email")

        if User.objects.filter(email=email).exists():

            raise ValidationError(
                "This email is already registered."
            )

        return email


    def clean_first_name(self):

        first_name = self.cleaned_data.get("first_name")

        if len(first_name.strip()) < 3:

            raise ValidationError(
                "Name must contain at least 3 characters."
            )

        return first_name


    class Meta:

        model = User

        fields = [
            "first_name",
            "email",
            "password1",
            "password2",
        ]
        widgets = {
            "first_name": forms.TextInput(),
            "email": forms.EmailInput(),
        }               

class LoginForm(forms.Form):

    email = forms.EmailField(

        widget=forms.EmailInput(

            attrs={

                "class": "form-control auth-input",

                "placeholder": "Enter your email address"

            }

        )

    )

    password = forms.CharField(

        widget=forms.PasswordInput(

            attrs={

                "class": "form-control auth-input",

                "placeholder": "Enter your password"

            }

        )

    ) 

    def clean_email(self):
        email = self.cleaned_data["email"].strip().lower()
        return email

    def clean_password(self):
        password = self.cleaned_data["password"]
        if password.strip() == "":
            raise ValidationError(
                "Password is required."
            )
        return password           