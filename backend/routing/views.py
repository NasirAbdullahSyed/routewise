import json
import logging
from django.http import JsonResponse, FileResponse, HttpResponse
from django.conf import settings
from django.views.decorators.http import require_POST, require_GET
from django.views.decorators.csrf import csrf_exempt
from .service import build_plan
from .providers import ProviderError, search_locations


@require_GET
def locations(request):
    query = request.GET.get("q", "").strip()
    if len(query) < 3:
        return JsonResponse({"results": []})
    if len(query) > 120:
        return JsonResponse({"error": "Enter a shorter city name."}, status=400)
    try:
        return JsonResponse({"results": search_locations(query)})
    except ProviderError:
        return JsonResponse(
            {"error": "Could not load location suggestions. Try again."}, status=502
        )


def health(request):
    return JsonResponse({"status": "ok"})


def index(request):
    file = settings.BASE_DIR / "dist" / "index.html"
    return (
        FileResponse(file.open("rb"), content_type="text/html")
        if file.exists()
        else HttpResponse(
            "Run npm run build or open the Vite development server.", status=503
        )
    )


@csrf_exempt  # Stateless public calculation endpoint: no cookies or user data.
@require_POST
def plan(request):
    if len(request.body) > 4096:
        return JsonResponse({"error": "Request is too large."}, status=413)
    try:
        data = json.loads(request.body)
        if not isinstance(data, dict):
            raise ValueError("Expected a JSON object.")
        return JsonResponse(build_plan(data))
    except (ValueError, TypeError) as exc:
        return JsonResponse({"error": str(exc)}, status=400)
    except ProviderError as exc:
        return JsonResponse({"error": str(exc)}, status=502)
    except Exception:
        logging.exception("Route planning failed")
        return JsonResponse(
            {"error": "Unable to plan this trip. Please retry."}, status=500
        )
