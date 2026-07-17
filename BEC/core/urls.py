from django.urls import include, path
from rest_framework.routers import DefaultRouter

from . import views

router = DefaultRouter()
router.register(r"accounts", views.AccountViewSet, basename="account")
router.register(r"reels", views.ReelViewSet, basename="reel")
router.register(r"tags", views.TagViewSet, basename="tag")
router.register(r"clusters", views.ClusterViewSet, basename="cluster")

urlpatterns = [
    path("auth/login/", views.login_view),
    path("auth/logout/", views.logout_view),
    path("auth/me/", views.me_view),
    path("stats/overview/", views.StatsView.as_view()),
    path("", include(router.urls)),
]
