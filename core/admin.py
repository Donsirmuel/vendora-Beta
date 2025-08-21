from django.contrib import admin
from .models import BrandProfile
# Register your models here.


@admin.register(BrandProfile)
class BrandProfileAdmin(admin.ModelAdmin):
    list_display = ("brand_name", "user", "currency_display", "created_at")