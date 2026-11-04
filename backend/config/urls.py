from django.urls import path, re_path
from routing.views import plan, index, health, locations

urlpatterns = [
    path("api/plan", plan),
    path("api/health", health),
    path("api/locations", locations),
    re_path(r"^(?!api/).*$", index),
]
