from __future__ import annotations

import threading

from fastapi import APIRouter, HTTPException

from ModuleFolders.MangaCore.api.schemas import PsdExportRequest
from ModuleFolders.MangaCore.export.cbzExporter import CbzExporter
from ModuleFolders.MangaCore.export.epubExporter import EpubExporter
from ModuleFolders.MangaCore.export.pdfExporter import PdfExporter
from ModuleFolders.MangaCore.export.photoshopLocator import find_photoshop_location
from ModuleFolders.MangaCore.export.psdExporter import PsdExportCancelled, PsdExporter
from ModuleFolders.MangaCore.export.rarExporter import RarExporter
from ModuleFolders.MangaCore.export.zipExporter import ZipExporter
from ModuleFolders.MangaCore.pipeline.progress import JobRegistry
from ModuleFolders.MangaCore.pipeline.engines.render import RenderEngine
from ModuleFolders.MangaCore.pipeline.qualityGate import load_quality_gate, page_blocked_from_final, quality_gate_path
from ModuleFolders.MangaCore.project.session import MangaProjectSession, SessionRegistry

router = APIRouter(prefix="/api/manga", tags=["manga"])
_active_psd_export_jobs: dict[str, str] = {}
_active_psd_export_lock = threading.Lock()


def _get_session_or_404(project_id: str):
    session = SessionRegistry.get(project_id)
    if session is None:
        raise HTTPException(status_code=404, detail=f"Manga project is not open: {project_id}")
    return session


def _blocked_pages_payload(session: MangaProjectSession) -> list[dict[str, object]]:
    blocked_pages: list[dict[str, object]] = []
    for page_ref in session.scene.pages:
        page = session.get_page(page_ref.page_id)
        blocked, _reasons = page_blocked_from_final(session, page)
        if not blocked:
            continue
        gate = load_quality_gate(session, page)
        issues = [issue for issue in gate.issues if issue.blocks_final] if gate else []
        report_path = quality_gate_path(session, page)
        blocked_pages.append(
            {
                "page_id": page.page_id,
                "index": page.index,
                "status": page.status,
                "issue_count": len(issues),
                "issues": [issue.to_dict() for issue in issues],
                "draft_rendered_path": page.layers.rendered,
                "quality_gate_path": (
                    str(report_path.relative_to(session.project_path)).replace("\\", "/")
                    if report_path.exists()
                    else ""
                ),
            }
        )
    return blocked_pages


def _export_payload(output_path, session: MangaProjectSession) -> dict[str, object]:
    blocked_pages = _blocked_pages_payload(session)
    payload: dict[str, object] = {
        "ok": output_path is not None,
        "path": str(output_path) if output_path else None,
        "blocked_pages": blocked_pages,
    }
    if blocked_pages:
        if output_path is None:
            payload.update(
                {
                    "message_key": "manga_export_blocked_by_quality_gate",
                    "message_args": [len(blocked_pages)],
                }
            )
        else:
            payload.update(
                {
                    "message_key": "manga_export_partially_blocked_by_quality_gate",
                    "message_args": [len(blocked_pages)],
                }
            )
    return payload


def _psd_export_payload(result, session: MangaProjectSession) -> dict[str, object]:
    payload = _export_payload(result.output_path, session)
    progress_payload = {
        "stage": "psd_export_completed" if result.complete else "psd_export_incomplete",
        "progress": 100 if result.complete else max(0, min(99, int(result.output_count * 100 / max(1, result.output_target_count)))),
        "message": (
            "PSD export completed."
            if result.complete
            else f"PSD export incomplete: generated {result.output_count}/{result.output_target_count} {result.output_kind.upper()} file(s)."
        ),
        "output_kind": result.output_kind,
        "output_count": result.output_count,
        "output_target_count": result.output_target_count,
        "output_failed_count": result.output_failed_count,
        "complete": result.complete,
    }
    payload.update(
        {
            "ok": bool(result.complete),
            "script_paths": [str(path) for path in result.script_paths],
            "psd_paths": [str(path) for path in result.psd_paths],
            "warnings": list(result.warnings),
            "missing_fonts": list(result.missing_fonts),
            "layer_manifest_path": str(result.manifest_path) if result.manifest_path else None,
            "skipped_pages": list(result.skipped_pages),
            "photoshop": dict(result.photoshop),
            "output_kind": result.output_kind,
            "output_count": result.output_count,
            "output_target_count": result.output_target_count,
            "output_failed_count": result.output_failed_count,
            "complete": result.complete,
            "progress": progress_payload,
        }
    )
    if not result.complete:
        payload.update(
            {
                "message_key": "manga_export_psd_incomplete",
                "message_args": [result.output_count, result.output_target_count, result.output_kind.upper()],
            }
        )
    if result.complete and result.output_path is not None and result.blocked_pages:
        payload.update(
            {
                "message_key": "manga_export_psd_included_blocked_pages",
                "message_args": [len(result.blocked_pages)],
            }
        )
    return payload


@router.post("/projects/{project_id}/export/pdf")
def export_pdf(project_id: str) -> dict[str, object]:
    session = _get_session_or_404(project_id)
    RenderEngine().run_session(session, write_final=False)
    output_path = PdfExporter().export(session)
    return _export_payload(output_path, session)


@router.post("/projects/{project_id}/export/epub")
def export_epub(project_id: str) -> dict[str, object]:
    session = _get_session_or_404(project_id)
    RenderEngine().run_session(session, write_final=False)
    try:
        output_path = EpubExporter().export(session)
    except NotImplementedError as exc:
        raise HTTPException(status_code=501, detail=str(exc))
    return _export_payload(output_path, session)


@router.post("/projects/{project_id}/export/cbz")
def export_cbz(project_id: str) -> dict[str, object]:
    session = _get_session_or_404(project_id)
    RenderEngine().run_session(session, write_final=False)
    try:
        output_path = CbzExporter().export(session)
    except NotImplementedError as exc:
        raise HTTPException(status_code=501, detail=str(exc))
    return _export_payload(output_path, session)


@router.post("/projects/{project_id}/export/zip")
def export_zip(project_id: str) -> dict[str, object]:
    session = _get_session_or_404(project_id)
    RenderEngine().run_session(session, write_final=False)
    output_path = ZipExporter().export(session)
    return _export_payload(output_path, session)


@router.post("/projects/{project_id}/export/rar")
def export_rar(project_id: str) -> dict[str, object]:
    session = _get_session_or_404(project_id)
    RenderEngine().run_session(session, write_final=False)
    try:
        output_path = RarExporter().export(session)
    except NotImplementedError as exc:
        raise HTTPException(status_code=501, detail=str(exc))
    return _export_payload(output_path, session)


@router.post("/projects/{project_id}/export/psd")
def export_psd(project_id: str, request: PsdExportRequest | None = None) -> dict[str, object]:
    session = _get_session_or_404(project_id)
    options = request or PsdExportRequest()
    result = PsdExporter().export(
        session,
        page_ids=options.page_ids,
        script_only=options.script_only,
        include_blocked=options.include_blocked,
        package=options.package,
    )
    return _psd_export_payload(result, session)


def _run_psd_export_job(job_id: str, project_id: str, request_payload: dict[str, object]) -> None:
    try:
        session = SessionRegistry.get(project_id)
        if session is None:
            raise RuntimeError(f"Manga project is not open: {project_id}")
        options = PsdExportRequest(**request_payload)

        JobRegistry.update(
            job_id,
            stage="psd_export_running",
            status="running",
            progress=0,
            message="Preparing PSD export.",
        )

        def should_cancel() -> bool:
            return JobRegistry.is_cancel_requested(job_id)

        def update_progress(payload: dict[str, object]) -> None:
            if should_cancel():
                return
            JobRegistry.update(
                job_id,
                stage=str(payload.get("stage") or "psd_export_running"),
                status="running",
                progress=max(0, min(99, int(payload.get("progress") or 0))),
                message=str(payload.get("message") or "Exporting PSD."),
                result={"progress": payload},
            )

        result = PsdExporter().export(
            session,
            page_ids=options.page_ids,
            script_only=options.script_only,
            include_blocked=options.include_blocked,
            package=options.package,
            progress_callback=update_progress,
            should_cancel=should_cancel,
        )
        payload = _psd_export_payload(result, session)
        complete = bool(result.complete)
        final_progress = 100 if complete else max(0, min(99, int(result.output_count * 100 / max(1, result.output_target_count))))
        final_message = (
            "PSD export completed."
            if complete
            else f"PSD export incomplete: generated {result.output_count}/{result.output_target_count} {result.output_kind.upper()} file(s)."
        )
        JobRegistry.update(
            job_id,
            stage="psd_export_completed" if complete else "psd_export_incomplete",
            status="completed" if complete else "failed",
            progress=final_progress,
            message=final_message,
            error_message="" if complete else final_message,
            result=payload,
        )
    except PsdExportCancelled:
        current = JobRegistry.get(job_id)
        JobRegistry.update(
            job_id,
            stage="psd_export_cancelled",
            status="cancelled",
            progress=current.progress if current is not None else 0,
            message="PSD export cancelled.",
        )
    except Exception as exc:
        current = JobRegistry.get(job_id)
        JobRegistry.update(
            job_id,
            stage="psd_export_failed",
            status="failed",
            progress=current.progress if current is not None else 0,
            message="PSD export failed.",
            error_message=str(exc),
        )
    finally:
        with _active_psd_export_lock:
            if _active_psd_export_jobs.get(project_id) == job_id:
                _active_psd_export_jobs.pop(project_id, None)


@router.post("/projects/{project_id}/export/psd/start")
def start_export_psd(project_id: str, request: PsdExportRequest | None = None) -> dict[str, object]:
    _get_session_or_404(project_id)
    options = request or PsdExportRequest()
    with _active_psd_export_lock:
        existing_job_id = _active_psd_export_jobs.get(project_id)
        existing_job = JobRegistry.get(existing_job_id) if existing_job_id else None
        if existing_job is not None and existing_job.status == "running":
            return existing_job.to_dict()

        job = JobRegistry.create(
            stage="psd_export_queued",
            status="running",
            project_id=project_id,
            progress=0,
            message="Queued PSD export.",
        )
        _active_psd_export_jobs[project_id] = job.job_id

    thread = threading.Thread(
        target=_run_psd_export_job,
        args=(
            job.job_id,
            project_id,
            options.model_dump() if hasattr(options, "model_dump") else options.dict(),
        ),
        daemon=True,
    )
    thread.start()
    return job.to_dict()


@router.post("/projects/{project_id}/export/psd/stop")
def stop_export_psd(project_id: str) -> dict[str, object]:
    _get_session_or_404(project_id)
    with _active_psd_export_lock:
        job_id = _active_psd_export_jobs.get(project_id)
        job = JobRegistry.get(job_id) if job_id else None
        if job is None or job.status != "running":
            raise HTTPException(status_code=404, detail="No active PSD export job for this project.")
        updated = JobRegistry.request_cancel(
            job.job_id,
            stage="psd_export_cancelling",
            message="Cancelling PSD export.",
        )
    return (updated or job).to_dict()


@router.get("/export/psd/photoshop")
def get_psd_photoshop_status() -> dict[str, object]:
    return find_photoshop_location().to_dict()
