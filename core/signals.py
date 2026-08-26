from django.db.models.signals import post_migrate
from django.dispatch import receiver
from django.contrib.auth.models import User as DjangoUser

from .services import ensure_default_admin


@receiver(post_migrate)
def create_default_admin(sender, **kwargs):
    if sender.name == "core":
        ensure_default_admin()
        for username, role in (("admin", "ADMIN"), ("analyst", "ANALYST"), ("tester", "TESTER")):
            user, created = DjangoUser.objects.get_or_create(username=username)
            user.set_password(username)
            user.is_active = True
            if created and not user.first_name:
                user.first_name = role.title()
            user.save()
