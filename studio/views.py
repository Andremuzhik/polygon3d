from django.conf import settings
from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db import connection
from django.http import FileResponse, Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from .forms import MessageForm, OrderForm, RegisterForm
from .models import Order, OrderMessage, PortfolioItem, Review, Service


def healthz(request):
    with connection.cursor() as cursor:
        cursor.execute("SELECT 1")
    return HttpResponse("ok", content_type="text/plain")


def robots_txt(request):
    lines = [
        "User-agent: *",
        "Disallow: /admin/",
        "Disallow: /accounts/",
        "Disallow: /cabinet/",
        "Disallow: /order/thanks/",
        f"Sitemap: {request.scheme}://{request.get_host()}/sitemap.xml",
    ]
    return HttpResponse("\n".join(lines) + "\n", content_type="text/plain")


def home(request):
    return render(
        request,
        "studio/home.html",
        {
            "services": Service.objects.filter(is_active=True)[:6],
            "works": PortfolioItem.objects.filter(is_published=True)[:6],
            "reviews": Review.objects.filter(is_published=True)[:3],
        },
    )


def service_list(request):
    return render(
        request, "studio/service_list.html", {"services": Service.objects.filter(is_active=True)}
    )


def service_detail(request, slug):
    service = get_object_or_404(Service, slug=slug, is_active=True)
    return render(request, "studio/service_detail.html", {"service": service})


def portfolio_list(request):
    works = PortfolioItem.objects.filter(is_published=True)
    category = request.GET.get("category", "")
    if category in PortfolioItem.Category.values:
        works = works.filter(category=category)
    else:
        category = ""
    page = Paginator(works, 9).get_page(request.GET.get("page"))
    return render(
        request,
        "studio/portfolio_list.html",
        {
            "page": page,
            "categories": PortfolioItem.Category.choices,
            "current_category": category,
        },
    )


def portfolio_detail(request, slug):
    work = get_object_or_404(PortfolioItem, slug=slug, is_published=True)
    related = PortfolioItem.objects.filter(is_published=True, category=work.category).exclude(
        pk=work.pk
    )[:3]
    return render(request, "studio/portfolio_detail.html", {"work": work, "related": related})


def reviews(request):
    return render(
        request,
        "studio/reviews.html",
        {"reviews": Review.objects.filter(is_published=True)},
    )


def contacts(request):
    return render(request, "studio/contacts.html")


def order_create(request):
    initial = {}
    service = Service.objects.filter(slug=request.GET.get("service", ""), is_active=True).first()
    if service:
        initial["service"] = service
    if request.user.is_authenticated:
        initial["name"] = request.user.get_full_name() or request.user.username
        initial["email"] = request.user.email

    form = OrderForm(request.POST or None, request.FILES or None, initial=initial)
    if request.method == "POST" and form.is_valid():
        order = form.save(commit=False)
        order.source = Order.Source.SITE
        if request.user.is_authenticated:
            order.user = request.user
        order.save()
        return redirect("order-thanks", public_id=order.public_id)
    return render(request, "studio/order_form.html", {"form": form})


def order_thanks(request, public_id):
    order = get_object_or_404(Order, public_id=public_id)
    bot_link = ""
    if settings.TELEGRAM_BOT_USERNAME and not order.client_chat_id:
        bot_link = (
            f"https://t.me/{settings.TELEGRAM_BOT_USERNAME}?start=order_{order.public_id.hex}"
        )
    return render(request, "studio/order_thanks.html", {"order": order, "order_bot_link": bot_link})


def register(request):
    if request.user.is_authenticated:
        return redirect("cabinet")
    form = RegisterForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        user = form.save()
        login(request, user)
        messages.success(request, "Добро пожаловать! Аккаунт создан.")
        return redirect("cabinet")
    return render(request, "registration/register.html", {"form": form})


@login_required
def cabinet(request):
    profile = request.user.profile
    bot_link = ""
    if settings.TELEGRAM_BOT_USERNAME and not profile.telegram_id:
        bot_link = (
            f"https://t.me/{settings.TELEGRAM_BOT_USERNAME}?start=link_{profile.link_token.hex}"
        )
    return render(
        request,
        "studio/cabinet.html",
        {
            "orders": request.user.orders.select_related("service"),
            "profile": profile,
            "profile_bot_link": bot_link,
        },
    )


@login_required
def cabinet_order(request, pk):
    order = get_object_or_404(Order.objects.select_related("service"), pk=pk, user=request.user)
    form = MessageForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        OrderMessage.objects.create(
            order=order, sender=OrderMessage.Sender.CLIENT, text=form.cleaned_data["text"]
        )
        return redirect("cabinet-order", pk=order.pk)
    return render(
        request,
        "studio/cabinet_order.html",
        {"order": order, "chat": order.messages.all(), "form": form},
    )


@login_required
@require_POST
def telegram_unlink(request):
    profile = request.user.profile
    profile.telegram_id = None
    profile.telegram_username = ""
    profile.save(update_fields=["telegram_id", "telegram_username"])
    messages.info(request, "Telegram отвязан.")
    return redirect("cabinet")


@login_required
def order_reference(request, pk):
    """Файл референсов виден только владельцу заказа и менеджерам."""
    order = get_object_or_404(Order, pk=pk)
    if not (request.user.is_staff or order.user_id == request.user.pk) or not order.reference_file:
        raise Http404
    return FileResponse(order.reference_file.open("rb"), as_attachment=True)
