from rest_framework.pagination import PageNumberPagination


class JournalPagination(PageNumberPagination):
    page_size = 20
    page_size_query_param = "page_size"
    max_page_size = 100


class TradePagination(JournalPagination):
    def get_page_size(self, request):
        # Larger pages are restricted to the lightweight, read-only representation.
        self.max_page_size = 1000 if request.query_params.get("compact") == "1" else 100
        return super().get_page_size(request)
