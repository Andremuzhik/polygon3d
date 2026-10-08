from django.conf import settings

# Скрипты и подключения — только свои. Исключения для model-viewer: gstatic (декодеры Draco/KTX2 для
# сжатых glTF-моделей) и 'wasm-unsafe-eval' (компиляция WebAssembly этих декодеров; обычный eval
# по-прежнему запрещён). Inline-стили разрешены: ими пользуется сам model-viewer, а XSS строится
# на скриптах, которые запрещены полностью.
CONTENT_SECURITY_POLICY = "; ".join(
    [
        "default-src 'self'",
        "script-src 'self' 'wasm-unsafe-eval' https://www.gstatic.com",
        "style-src 'self' 'unsafe-inline'",
        "img-src 'self' data: blob:",
        "font-src 'self'",
        "connect-src 'self' data: blob: https://www.gstatic.com",
        "worker-src 'self' blob:",
        "object-src 'none'",
        "base-uri 'self'",
        "form-action 'self'",
        "frame-ancestors 'none'",
    ]
)
PERMISSIONS_POLICY = "camera=(), microphone=(), geolocation=(), payment=(), usb=()"


class SecurityHeadersMiddleware:
    """CSP для сайта (админка Django использует inline-скрипты, поэтому её не трогаем)."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        response.headers.setdefault("Permissions-Policy", PERMISSIONS_POLICY)
        is_admin = request.path.startswith("/admin/")
        is_debug_error_page = (
            settings.DEBUG and response.status_code >= 400
        )  # технические страницы Django
        if not is_admin and not is_debug_error_page:
            response.headers.setdefault("Content-Security-Policy", CONTENT_SECURITY_POLICY)
        return response
