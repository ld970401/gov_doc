"""
会话（对话）API：列表、详情、创建、重命名、删除，以及 **运行** 与 **SSE 事件流**。

- 前缀：/api/agentloop/conversations
- POST /run：自动创建会话并运行（推荐新入口）
- POST /{id}/run：运行已有会话（保留旧入口）
- GET /{id}/events：text/event-stream，按 seq_no 递增推送 V4TaskEvent，结束发送 data: [DONE]
"""

import json
import time
from datetime import datetime

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..auth import get_current_user
from ..db import SessionLocal, get_db
from ..debug_log import mask_cookie
from ..models import (
    V4Conversation,
    V4ConversationRun,
    V4TaskEvent,
)
from ..runtime import (
    execute_prepared_run,
    prepare_run_conversation,
)
from ..schemas import (
    AgentLoopResponse,
    ConversationCreateRequest,
    ConversationRenameRequest,
    ConversationRunRequest,
)

router = APIRouter(prefix="/api/agentloop/conversations", tags=["agentloop-conversations"])


def _conversation_or_404(db: Session, conversation_id: str, user_id: str) -> V4Conversation:
    conversation = db.execute(
        select(V4Conversation).where(
            V4Conversation.id == conversation_id,
            V4Conversation.user_id == user_id,
            V4Conversation.is_deleted.is_(False),
        )
    ).scalar_one_or_none()
    if conversation is None:
        raise HTTPException(status_code=404, detail="会话不存在")
    return conversation


@router.get("", response_model=AgentLoopResponse)
def list_conversations(current_user=Depends(get_current_user), db: Session = Depends(get_db)):
    items = db.execute(
        select(V4Conversation)
        .where(
            V4Conversation.user_id == current_user.user_id,
            V4Conversation.is_deleted.is_(False),
        )
        .order_by(V4Conversation.pinned.desc(), V4Conversation.last_message_at.desc())
    ).scalars().all()
    return AgentLoopResponse(
        data=[
            {
                "id": item.id,
                "title": item.title,
                "pinned": item.pinned,
                "lastMessageAt": item.last_message_at.isoformat(),
                "lastRunId": item.last_run_id,
            }
            for item in items
        ]
    )


@router.post("", response_model=AgentLoopResponse)
def create_conversation(
    request: ConversationCreateRequest,
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    conversation = V4Conversation(
        user_id=current_user.user_id,
        title=request.title or "新对话",
    )
    db.add(conversation)
    db.commit()
    db.refresh(conversation)
    return AgentLoopResponse(
        data={
            "id": conversation.id,
            "title": conversation.title,
            "createdAt": conversation.created_at.isoformat(),
        }
    )


@router.delete("/{conversation_id}", response_model=AgentLoopResponse)
def delete_conversation(
    conversation_id: str,
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    conversation = _conversation_or_404(db, conversation_id, current_user.user_id)
    conversation.is_deleted = True
    conversation.updated_at = datetime.utcnow()
    db.commit()
    return AgentLoopResponse(data={"id": conversation_id})


@router.patch("/{conversation_id}", response_model=AgentLoopResponse)
def rename_conversation(
    conversation_id: str,
    request: ConversationRenameRequest,
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    conversation = _conversation_or_404(db, conversation_id, current_user.user_id)
    if request.title is not None:
        conversation.title = request.title
    if request.pinned is not None:
        conversation.pinned = request.pinned
    conversation.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(conversation)
    return AgentLoopResponse(
        data={
            "id": conversation.id,
            "title": conversation.title,
            "pinned": conversation.pinned,
        }
    )


@router.post("/run", response_model=AgentLoopResponse)
def run_conversation_auto_create(
    request: ConversationRunRequest,
    background_tasks: BackgroundTasks,
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
    req: Request = None,
):
    cookies = req.headers.get("cookie") if req else None
    conversation = V4Conversation(
        user_id=current_user.user_id,
        title=request.title or "新对话",
    )
    db.add(conversation)
    db.commit()
    db.refresh(conversation)
    result = prepare_run_conversation(
        db,
        conversation,
        current_user,
        content=request.content,
        requested_skill=request.skill,
        requested_model=request.model,
        attachments=request.attachments,
        cookies=cookies,
        resume_from_waiting=request.resume_from_waiting,
        selected_option=request.selected_option,
        prompt_menu_input=request.prompt_menu_input,
    )
    run = result["run"]
    background_tasks.add_task(
        execute_prepared_run,
        run_id=run.id,
        task_id=run.task_id,
        conversation_id=conversation.id,
        current_user=current_user,
        content=request.content,
        requested_skill=request.skill,
        requested_model=request.model,
        attachments=request.attachments,
        cookies=cookies,
        resume_from_waiting=request.resume_from_waiting,
        selected_option=request.selected_option,
        prompt_menu_input=request.prompt_menu_input,
    )
    return AgentLoopResponse(
        data={
            "conversationId": conversation.id,
            "runId": run.id,
            "streamUrl": f"/api/agentloop/conversations/{conversation.id}/runs/{run.id}/events",
        }
    )


@router.post("/{conversation_id}/run", response_model=AgentLoopResponse)
def run_existing_conversation(
    conversation_id: str,
    request: ConversationRunRequest,
    background_tasks: BackgroundTasks,
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
    req: Request = None,
):
    conversation = _conversation_or_404(db, conversation_id, current_user.user_id)
    cookies = req.headers.get("cookie") if req else None
    result = prepare_run_conversation(
        db,
        conversation,
        current_user,
        content=request.content,
        requested_skill=request.skill,
        requested_model=request.model,
        attachments=request.attachments,
        cookies=cookies,
        resume_from_waiting=request.resume_from_waiting,
        selected_option=request.selected_option,
        prompt_menu_input=request.prompt_menu_input,
    )
    run = result["run"]
    background_tasks.add_task(
        execute_prepared_run,
        run_id=run.id,
        task_id=run.task_id,
        conversation_id=conversation.id,
        current_user=current_user,
        content=request.content,
        requested_skill=request.skill,
        requested_model=request.model,
        attachments=request.attachments,
        cookies=cookies,
        resume_from_waiting=request.resume_from_waiting,
        selected_option=request.selected_option,
        prompt_menu_input=request.prompt_menu_input,
    )
    return AgentLoopResponse(
        data={
            "conversationId": conversation.id,
            "runId": run.id,
            "streamUrl": f"/api/agentloop/conversations/{conversation.id}/runs/{run.id}/events",
        }
    )


@router.get("/{conversation_id}/runs/{run_id}/events")
def stream_events(
    conversation_id: str,
    run_id: str,
    current_user=Depends(get_current_user),
    req: Request = None,
):
    db = SessionLocal()
    try:
        conversation = _conversation_or_404(db, conversation_id, current_user.user_id)
        run = db.execute(
            select(V4ConversationRun).where(
                V4ConversationRun.id == run_id,
                V4ConversationRun.conversation_id == conversation.id,
                V4ConversationRun.user_id == current_user.user_id,
            )
        ).scalar_one_or_none()
        if run is None:
            raise HTTPException(status_code=404, detail="运行记录不存在")
    finally:
        db.close()

    def event_stream():
        stream_db = SessionLocal()
        sent_seq_no = 0
        last_heartbeat = time.monotonic()
        try:
            while True:
                stream_db.rollback()
                current_run = stream_db.execute(
                    select(V4ConversationRun).where(
                        V4ConversationRun.id == run.id,
                        V4ConversationRun.conversation_id == conversation.id,
                        V4ConversationRun.user_id == current_user.user_id,
                    )
                ).scalar_one_or_none()
                if current_run is None:
                    yield "data: [DONE]\n\n"
                    return

                events = stream_db.execute(
                    select(V4TaskEvent)
                    .where(V4TaskEvent.run_id == run.id, V4TaskEvent.seq_no > sent_seq_no)
                    .order_by(V4TaskEvent.seq_no.asc())
                ).scalars().all()

                for event in events:
                    output = {
                        "type": event.event_type,
                    }
                    if event.event_type == "content_block_start" and event.block_json:
                        block = json.loads(event.block_json)
                        if isinstance(block, dict):
                            block.pop("stepIndex", None)
                            block.pop("stepTitle", None)
                            block.pop("name", None)
                        output["content_block"] = block
                    elif event.event_type == "content_block_delta" and event.delta_json:
                        output["delta"] = json.loads(event.delta_json)
                    elif event.event_type == "tool_result" and event.payload_json:
                        payload = json.loads(event.payload_json)
                        if isinstance(payload, dict):
                            payload.pop("plannerMeta", None)
                            payload.pop("taskId", None)
                            payload.pop("parentTaskId", None)
                            if payload.get("tool") == "a2a_planning":
                                plan = payload.get("plan")
                                if isinstance(plan, dict):
                                    for key in ("summary", "requiresUserInput", "clarificationQuestion"):
                                        plan.pop(key, None)
                                    steps = plan.get("steps")
                                    if isinstance(steps, list):
                                        for step in steps:
                                            if not isinstance(step, dict):
                                                continue
                                            for key in (
                                                "title",
                                                "displayTitle",
                                                "actionLabel",
                                                "pendingLabel",
                                                "runningLabel",
                                                "doneLabel",
                                            ):
                                                step.pop(key, None)
                        output["payload"] = payload
                    elif event.event_type == "message_start":
                        # 需求：首条 message_start 不回传 payload
                        pass
                    elif event.event_type == "message_delta" and event.payload_json:
                        output["payload"] = json.loads(event.payload_json)
                    elif event.event_type == "waiting_user" and event.payload_json:
                        output["payload"] = json.loads(event.payload_json)
                    elif event.event_type == "error" and event.payload_json:
                        output["payload"] = json.loads(event.payload_json)
                    elif event.event_type == "running" and event.payload_json:
                        payload = json.loads(event.payload_json)
                        if isinstance(payload, dict):
                            payload.pop("taskId", None)
                            payload.pop("parentTaskId", None)
                        output["payload"] = payload
                    yield "data: " + json.dumps(output, ensure_ascii=False) + "\n\n"
                    sent_seq_no = event.seq_no
                    last_heartbeat = time.monotonic()

                if current_run.status in {"completed", "failed", "waiting_user"}:
                    yield "data: [DONE]\n\n"
                    return

                now = time.monotonic()
                if (now - last_heartbeat) >= 1.0:
                    last_heartbeat = now

                stream_db.expire_all()
                time.sleep(0.25)
        finally:
            stream_db.close()

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream; charset=utf-8",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
