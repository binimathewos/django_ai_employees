from django.shortcuts import get_object_or_404, render
from . models import Order, RefundRequest
from django.contrib.auth.decorators import login_required


@login_required
def order_list(request):
    orders = Order.objects.filter(user=request.user)
    context = {
        'orders': orders
    }
    return render(request, 'orders_list.html', context)


@login_required
def order_detail(request, order_id):
    order = get_object_or_404(Order, id=order_id, user=request.user)
    refund_requests = RefundRequest.objects.filter(order=order)
    context = {
        'order': order,
        'refunds': refund_requests
    }
    return render(request, 'order_detail.html', context)
