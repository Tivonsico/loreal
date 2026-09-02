from fastapi import HTTPException, Request, status


def require_customer_service(request: Request) -> None:
    if request.app.state.settings.role != "customer_service":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="该操作仅供客服工作台使用",
        )
