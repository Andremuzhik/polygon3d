from django.conf import settings


def site(request):
    username = settings.TELEGRAM_BOT_USERNAME
    return {
        "SITE_NAME": settings.SITE_NAME,
        "CONTACT_EMAIL": settings.CONTACT_EMAIL,
        "CONTACT_PHONE": settings.CONTACT_PHONE,
        "BOT_URL": f"https://t.me/{username}" if username else "",
        "BOT_USERNAME": username,
    }
