# -*- coding: utf-8 -*-
"""
===================================
健康检查接口 (已废弃)
===================================

注意：此模块已不再通过 api/v1/router.py 注册，实际的健康检查接口
定义在 api/app.py 中的 /api/health 路由。

保留此文件仅作为历史参考，功能上完全由 api/app.py 的 health_check 端点覆盖。
如需重新启用 /api/v1/health，请在 api/v1/router.py 中添加：
    from api.v1.endpoints import health
    router.include_router(health.router, prefix="/health", tags=["Health"])
"""

from datetime import datetime

from fastapi import APIRouter

from api.v1.schemas.common import HealthResponse

router = APIRouter()


@router.get("/health", response_model=HealthResponse)
async def health_check() -> HealthResponse:
    """
    健康检查接口
    
    用于负载均衡器或监控系统检查服务状态
    
    Returns:
        HealthResponse: 包含服务状态和时间戳
    """
    return HealthResponse(
        status="ok",
        timestamp=datetime.now().isoformat()
    )
