import django_filters as df

from . import models


# FEC scope names → account owner_type
SCOPE_MAP = {"medyca": "owned", "owned": "owned",
             "competitor": "competitor", "competitors": "competitor"}


class ReelFilter(df.FilterSet):
    account = df.NumberFilter(field_name="account_id")
    account_username = df.CharFilter(field_name="account__username", lookup_expr="iexact")
    scope = df.CharFilter(method="filter_scope")
    content_format = df.CharFilter(field_name="enrichment__content_format")
    favorite = df.BooleanFilter(field_name="annotation__is_favorite")
    inspiration = df.BooleanFilter(field_name="annotation__is_inspiration")
    tag = df.NumberFilter(field_name="annotation__tags__id")
    cluster = df.NumberFilter(method="filter_cluster")
    posted_after = df.DateTimeFilter(field_name="posted_at", lookup_expr="gte")
    posted_before = df.DateTimeFilter(field_name="posted_at", lookup_expr="lte")
    transcribed = df.BooleanFilter(method="filter_transcribed")

    class Meta:
        model = models.Reel
        fields = []

    def filter_scope(self, queryset, name, value):
        owner = SCOPE_MAP.get((value or "").lower())
        if not owner:
            return queryset
        return queryset.filter(account__owner_type=owner)

    def filter_cluster(self, queryset, name, value):
        # Resolve the cluster within its own scope's current run.
        cluster = models.TopicCluster.objects.filter(id=value).select_related("run").first()
        if not cluster:
            return queryset.none()
        return queryset.filter(
            cluster_assignments__run=cluster.run, cluster_assignments__cluster_id=value
        )

    def filter_transcribed(self, queryset, name, value):
        if value:
            return queryset.filter(transcribe_status=models.DONE)
        return queryset
