from django.contrib import admin
from .models import Conversation, Message, AgentLog


class ConversationAdmin(admin.ModelAdmin):
    list_display = ['id', 'user', 'order', 'created_at']


class MessageAdmin(admin.ModelAdmin):
    list_display = ['id', 'conversation', 'role', 'content', 'created_at']


class AgentLogAdmin(admin.ModelAdmin):
    list_display = ['id', 'conversation',
                    'event_type', 'message', 'created_at']


admin.site.register(Conversation, ConversationAdmin)
admin.site.register(Message, MessageAdmin)
admin.site.register(AgentLog, AgentLogAdmin)
