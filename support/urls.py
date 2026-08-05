from django.urls import path
from . import views

urlpatterns = [
    # This will route the root URL of the support app to the views in support/views.py
    path("chat/<int:order_id>/", views.chat, name="chat"),
    path("dashboard/", views.dashboard, name="dashboard"),
    path("dashboard/<int:conversation_id>/",
         views.conversation_detail, name="conversation_detail"),
    path("dashboard/stream/<int:conversation_id>/",
         views.conversation_stream, name="conversation_stream")
]
