from trace_core.core.database.session import DatabaseSessionManager


def forensic_operation_active(session_manager: DatabaseSessionManager | None = None) -> bool:
    from trace_core.core.database.session import db_manager
    from trace_core.imaging.repository import SqlAlchemyImagingRepository

    manager = session_manager or db_manager
    with manager.session() as session:
        return SqlAlchemyImagingRepository(session).has_any_blocking_operation()
