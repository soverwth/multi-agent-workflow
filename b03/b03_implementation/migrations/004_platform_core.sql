-- B03 平台核心存储迁移（通用，与具体案例无关）
-- 目标：项目隔离、需求/设计/计划版本、运行与执行尝试、执行日志/产物/证据/验收、
--       事件幂等与回放、按项目/运行的 checkpoint。
-- 说明：本迁移使用独立数据库 PLATFORM_DB，不与校园案例业务库混用。

CREATE TABLE IF NOT EXISTS projects (
    project_id   TEXT PRIMARY KEY,
    name         TEXT NOT NULL,
    goal         TEXT,
    created_at   TEXT NOT NULL,
    metadata_json TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS project_versions (
    version_id    TEXT PRIMARY KEY,
    project_id    TEXT NOT NULL REFERENCES projects(project_id),
    version_kind  TEXT NOT NULL,   -- requirement | design | plan
    version_label TEXT NOT NULL,   -- 如 R1 / S1 / plan_v2
    content_json  TEXT NOT NULL,
    created_at    TEXT NOT NULL,
    UNIQUE (project_id, version_kind, version_label)
);
CREATE INDEX IF NOT EXISTS idx_pv_project_kind ON project_versions(project_id, version_kind);

CREATE TABLE IF NOT EXISTS task_runs (
    run_id      TEXT PRIMARY KEY,
    project_id  TEXT NOT NULL REFERENCES projects(project_id),
    plan_version TEXT NOT NULL,
    status      TEXT NOT NULL,   -- RUNNING | PAUSED | COMPLETED | CANCELLED
    started_at  TEXT NOT NULL,
    finished_at TEXT,
    metadata_json TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_runs_project ON task_runs(project_id, started_at);

CREATE TABLE IF NOT EXISTS task_attempts (
    attempt_id   TEXT PRIMARY KEY,
    run_id       TEXT NOT NULL REFERENCES task_runs(run_id),
    project_id   TEXT NOT NULL REFERENCES projects(project_id),
    task_id      TEXT NOT NULL,
    attempt_no   INTEGER NOT NULL,
    agent_role   TEXT,
    state        TEXT NOT NULL,   -- PENDING/READY/RUNNING/REVIEWING/SUCCEEDED/FAILED
    input_snapshot_json TEXT NOT NULL DEFAULT '{}',
    started_at   TEXT,
    finished_at  TEXT,
    result_json  TEXT NOT NULL DEFAULT '{}',
    UNIQUE (run_id, task_id, attempt_no)
);
CREATE INDEX IF NOT EXISTS idx_att_project_task ON task_attempts(project_id, task_id);
CREATE INDEX IF NOT EXISTS idx_att_run ON task_attempts(run_id);

CREATE TABLE IF NOT EXISTS execution_logs (
    log_id      TEXT PRIMARY KEY,
    project_id  TEXT NOT NULL REFERENCES projects(project_id),
    run_id      TEXT,
    attempt_id  TEXT,
    level       TEXT NOT NULL DEFAULT 'INFO',
    message     TEXT NOT NULL,
    context_json TEXT NOT NULL DEFAULT '{}',
    created_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_logs_project ON execution_logs(project_id, created_at);

CREATE TABLE IF NOT EXISTS platform_artifacts (
    artifact_id  TEXT PRIMARY KEY,
    project_id   TEXT NOT NULL REFERENCES projects(project_id),
    run_id       TEXT,
    attempt_id   TEXT,
    task_id      TEXT NOT NULL,
    version      TEXT NOT NULL,
    path         TEXT,
    content_hash TEXT,
    commit_ref   TEXT,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at   TEXT NOT NULL,
    UNIQUE (project_id, task_id, attempt_id, version)
);
CREATE INDEX IF NOT EXISTS idx_pa_project_task ON platform_artifacts(project_id, task_id);

CREATE TABLE IF NOT EXISTS evidence_records (
    evidence_id  TEXT PRIMARY KEY,
    project_id   TEXT NOT NULL REFERENCES projects(project_id),
    task_id      TEXT NOT NULL,
    attempt_id   TEXT,
    test_id      TEXT NOT NULL,
    input_json   TEXT NOT NULL DEFAULT '{}',
    expected     TEXT,
    actual       TEXT,
    env          TEXT,
    artifact_ref TEXT,
    verdict      TEXT NOT NULL,   -- PASS | FAIL
    created_at   TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_ev_project_task ON evidence_records(project_id, task_id);

CREATE TABLE IF NOT EXISTS acceptance_results (
    acceptance_id TEXT PRIMARY KEY,
    project_id    TEXT NOT NULL REFERENCES projects(project_id),
    task_id       TEXT NOT NULL,
    attempt_id    TEXT,
    verdict       TEXT NOT NULL,  -- ACCEPT | REJECT | REVALIDATION_REQUIRED
    reason        TEXT,
    evidence_refs_json TEXT NOT NULL DEFAULT '[]',
    defect_json   TEXT NOT NULL DEFAULT '{}',
    created_at    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_acc_project_task ON acceptance_results(project_id, task_id);

CREATE TABLE IF NOT EXISTS platform_events (
    seq          INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id     TEXT NOT NULL UNIQUE,   -- 幂等键
    project_id   TEXT NOT NULL REFERENCES projects(project_id),
    run_id       TEXT,
    task_id      TEXT,
    attempt_id   TEXT,
    event_type   TEXT NOT NULL,
    payload_json TEXT NOT NULL DEFAULT '{}',
    input_version_json TEXT NOT NULL DEFAULT '{}',
    occurred_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_pe_project_seq ON platform_events(project_id, seq);

CREATE TABLE IF NOT EXISTS platform_checkpoints (
    project_id   TEXT NOT NULL REFERENCES projects(project_id),
    run_id       TEXT NOT NULL REFERENCES task_runs(run_id),
    checkpoint_id TEXT NOT NULL,
    state_json   TEXT NOT NULL,
    processed_event_seq INTEGER NOT NULL DEFAULT 0,
    created_at   TEXT NOT NULL,
    PRIMARY KEY (project_id, run_id, checkpoint_id)
);
CREATE INDEX IF NOT EXISTS idx_cp_project_run ON platform_checkpoints(project_id, run_id, checkpoint_id);
