from fastapi import APIRouter, Depends
from fastapi.responses import Response
from sqlalchemy.orm import Session

from backend.openloop.api.schemas import (
    LayoutBulkReplace,
    LayoutResponse,
    WidgetCreate,
    WidgetResponse,
    WidgetUpdate,
)
from backend.openloop.database import get_db
from backend.openloop.services import layout_service

router = APIRouter(prefix="/api/v1/spaces", tags=["layouts"])


@router.get("/{space_id}/layout", response_model=LayoutResponse)
def get_layout(space_id: str, db: Session = Depends(get_db)) -> LayoutResponse:
    widgets = layout_service.get_layout(db, space_id)
    return LayoutResponse(widgets=[WidgetResponse.model_validate(w) for w in widgets])


@router.post("/{space_id}/layout/widgets", response_model=WidgetResponse, status_code=201)
def add_widget(space_id: str, body: WidgetCreate, db: Session = Depends(get_db)) -> WidgetResponse:
    widget = layout_service.add_widget(
        db,
        space_id,
        widget_type=body.widget_type.value,
        position=body.position,
        size=body.size.value,
        config=body.config,
    )
    return WidgetResponse.model_validate(widget)


@router.patch("/{space_id}/layout/widgets/{widget_id}", response_model=WidgetResponse)
def update_widget(
    space_id: str, widget_id: str, body: WidgetUpdate, db: Session = Depends(get_db)
) -> WidgetResponse:
    updates = body.model_dump(exclude_unset=True)
    # Convert enum values to strings for storage
    if "size" in updates and updates["size"] is not None:
        updates["size"] = updates["size"].value
    widget = layout_service.update_widget(db, space_id, widget_id, **updates)
    return WidgetResponse.model_validate(widget)


@router.delete("/{space_id}/layout/widgets/{widget_id}", status_code=204)
def remove_widget(space_id: str, widget_id: str, db: Session = Depends(get_db)) -> Response:
    layout_service.remove_widget(db, space_id, widget_id)
    return Response(status_code=204)


@router.put("/{space_id}/layout", response_model=LayoutResponse)
def set_layout(space_id: str, body: LayoutBulkReplace, db: Session = Depends(get_db)) -> LayoutResponse:
    widget_dicts = [
        {
            "widget_type": w.widget_type.value,
            "position": w.position,
            "size": w.size.value,
            "config": w.config,
        }
        for w in body.widgets
    ]
    widgets = layout_service.set_layout(db, space_id, widget_dicts)
    return LayoutResponse(widgets=[WidgetResponse.model_validate(w) for w in widgets])
