from typing import Final

TOOL_STATUS: Final = "trace_status"
TOOL_CASE_GET: Final = "trace_case_get"
TOOL_CASE_LIST: Final = "trace_case_list"
TOOL_CASE_CREATE: Final = "trace_case_create"
TOOL_CASE_UPDATE: Final = "trace_case_update"
TOOL_CASE_REVIEW: Final = "trace_case_review"
TOOL_CASE_CLOSE: Final = "trace_case_close"
TOOL_CASE_ARCHIVE: Final = "trace_case_archive"
TOOL_CASE_RESTORE: Final = "trace_case_restore"
TOOL_CASE_PURGE: Final = "trace_case_purge"
TOOL_AUDIT_LIST: Final = "trace_audit_list"
TOOL_AUDIT_GET: Final = "trace_audit_get"
TOOL_AUDIT_VERIFY: Final = "trace_audit_verify"
TOOL_AUDIT_EXPORT: Final = "trace_audit_export"
TOOL_AUDIT_DECRYPT: Final = "trace_audit_decrypt"
TOOL_AUDIT_KEYS_INIT: Final = "trace_audit_keys_init"
TOOL_AUDIT_KEYS_ROTATE: Final = "trace_audit_keys_rotate"
TOOL_AUDIT_KEYS_LIST: Final = "trace_audit_keys_list"
TOOL_DEVICE_LIST: Final = "trace_device_list"
TOOL_DEVICE_OBSERVED: Final = "trace_device_observed"
TOOL_DEVICE_HISTORY: Final = "trace_device_history"
TOOL_DEVICE_LINKS: Final = "trace_device_links"
TOOL_DEVICE_LINK: Final = "trace_device_link"
TOOL_DEVICE_UNLINK: Final = "trace_device_unlink"
TOOL_UPDATE_INSTALL: Final = "trace_update_install"
TOOL_UNINSTALL: Final = "trace_uninstall"
TOOL_RECOVERY: Final = "trace_recovery"
TOOL_DB_MIGRATE: Final = "trace_db_migrate"

READ_TOOLS: Final[frozenset[str]] = frozenset(
    {
        TOOL_STATUS,
        TOOL_CASE_GET,
        TOOL_CASE_LIST,
        TOOL_AUDIT_LIST,
        TOOL_AUDIT_GET,
        TOOL_AUDIT_VERIFY,
        TOOL_AUDIT_KEYS_LIST,
        TOOL_DEVICE_LIST,
        TOOL_DEVICE_OBSERVED,
        TOOL_DEVICE_HISTORY,
        TOOL_DEVICE_LINKS,
    }
)

WRITE_TOOLS: Final[frozenset[str]] = frozenset(
    {
        TOOL_CASE_CREATE,
        TOOL_CASE_UPDATE,
        TOOL_CASE_REVIEW,
        TOOL_CASE_CLOSE,
        TOOL_CASE_ARCHIVE,
        TOOL_CASE_RESTORE,
        TOOL_DEVICE_LINK,
        TOOL_DEVICE_UNLINK,
    }
)

OVERRIDE_TOOLS: Final[frozenset[str]] = frozenset(
    {
        TOOL_CASE_PURGE,
        TOOL_AUDIT_EXPORT,
        TOOL_AUDIT_DECRYPT,
        TOOL_AUDIT_KEYS_INIT,
        TOOL_AUDIT_KEYS_ROTATE,
        TOOL_UPDATE_INSTALL,
        TOOL_UNINSTALL,
        TOOL_RECOVERY,
        TOOL_DB_MIGRATE,
    }
)

ALL_TOOLS: Final[frozenset[str]] = READ_TOOLS | WRITE_TOOLS | OVERRIDE_TOOLS

CONFIRM_UNINSTALL: Final = "UNINSTALL"
CONFIRM_RECOVERY: Final = "RECOVER"
CONFIRM_MIGRATE: Final = "MIGRATE"
CONFIRM_UPDATE: Final = "UPDATE"
CONFIRM_OVERWRITE: Final = "OVERWRITE"
