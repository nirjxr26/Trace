from mcp.server import MCPServer


def register(server: MCPServer) -> None:
    @server.prompt(
        "case_triage",
        description="Summarize a case using read-only MCP tools before any state change.",
    )
    def case_triage(case_number: str) -> str:
        return (
            f"Review case {case_number}. Use trace_case_get for the current state, "
            "trace_audit_list for the five newest events, and trace_device_links for linked devices. "
            "Report state, lead examiner, recent activity, and linked devices. "
            "Do not call write or destructive tools."
        )

    @server.prompt(
        "audit_integrity_report",
        description="Summarize ledger verification for a case without mutating anything.",
    )
    def audit_integrity_report(case_number: str) -> str:
        return (
            f"Check the audit ledger for case {case_number}. Use trace_audit_verify once, "
            "then trace_audit_list with detail=summary and limit=20. "
            "Report whether the chain is intact and list the newest events. "
            "Do not export, rotate keys, or change case state."
        )

    @server.prompt(
        "device_intake_checklist",
        description="Read-only checklist for a device before any acquisition decision.",
    )
    def device_intake_checklist(serial: str) -> str:
        return (
            f"Review device {serial}. Use trace_device_observed for the observed device list and "
            f"trace_device_history with serial={serial}. "
            "Report the newest observation, prior observations, and whether a write-protection verdict exists. "
            "If the verdict is absent or UNKNOWN, state that human confirmation is required. "
            "Do not request hardware access or acquisition."
        )
