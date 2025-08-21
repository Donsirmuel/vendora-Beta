from django.db import models
from django.conf import settings
# Create your models here.

class BrandProfile(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='brand')
    brand_name = models.CharField(max_length=255)
    logo = models.ImageField(upload_to='logos/', blank=True, null=True)
    currency_display = models.CharField(max_length=3, choices=[('NGN','NGN'),('USD','USD')], default='NGN')
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.brand_name