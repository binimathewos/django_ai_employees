from django.urls import path
from . import views

urlpatterns = [
    # This will route the root URL of the support app to the views in support/views.py
    path("chat/<int:order_id>/", views.chat, name="chat"),
]
