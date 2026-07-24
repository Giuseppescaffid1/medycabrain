from django.urls import include, path
from rest_framework.routers import DefaultRouter

from . import views

router = DefaultRouter()
router.register(r"accounts", views.AccountViewSet, basename="account")
router.register(r"reels", views.ReelViewSet, basename="reel")
router.register(r"tags", views.TagViewSet, basename="tag")
router.register(r"clusters", views.ClusterViewSet, basename="cluster")
router.register(r"knowledge/documents", views.KnowledgeDocumentViewSet, basename="knowledge-doc")
router.register(r"second-brain/ideas", views.ContentIdeaViewSet, basename="content-idea")
router.register(r"second-brain/blog-drafts", views.BlogDraftViewSet, basename="blog-draft")
router.register(r"jobs", views.JobViewSet, basename="job")

urlpatterns = [
    path("auth/login/", views.login_view),
    path("auth/logout/", views.logout_view),
    path("auth/me/", views.me_view),
    path("stats/overview/", views.StatsView.as_view()),
    path("knowledge/search/", views.KnowledgeSearchView.as_view()),
    path("knowledge/ask/", views.KnowledgeAskView.as_view()),
    path("", include(router.urls)),
]
