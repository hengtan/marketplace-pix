from __future__ import annotations

from marketplace_common.security import Principal, Scope

from ordering.domain.order import Order


def can_view_order(order: Order, principal: Principal | None) -> bool:
    if order.is_guest:
        return True
    if principal is None:
        return False
    return principal.can(Scope.ORDERS_READ_ANY) or order.is_owned_by(principal.user_id)
