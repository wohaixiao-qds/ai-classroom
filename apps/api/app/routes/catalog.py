"""课表路由:GET /api/v1/catalog(四泳道)+ POST /api/v1/catalog/action(记意图)。

点击动作只落「意图」(Option B):备课=P2、调研=P3 未建时先接住不造逻辑;
确认/忽略维护衍生候选池。都不碰只读 vault。
"""

from __future__ import annotations

from fastapi import APIRouter

from app.core.catalog_store import record_action
from app.schemas.catalog import ActionResult, Catalog, CatalogAction
from app.services.catalog import build_catalog

router = APIRouter(prefix="/api/v1", tags=["catalog"])


@router.get("/catalog", response_model=Catalog)
def catalog() -> Catalog:
    """学习指挥台:四泳道(在学 / 能学 / 想学 / 刚冒出)。"""
    return build_catalog()


@router.post("/catalog/action", response_model=ActionResult)
def catalog_action(req: CatalogAction) -> ActionResult:
    """记录课表点击意图(确认候选 / 请求备课 / 请求调研)。"""
    row = record_action(req.kind, req.target, req.label)
    return ActionResult(**row)
