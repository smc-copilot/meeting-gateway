BEGIN;

CREATE TABLE alembic_version (
    version_num VARCHAR(32) NOT NULL, 
    CONSTRAINT alembic_version_pkc PRIMARY KEY (version_num)
);

-- Running upgrade  -> 1d4f7c955b82

CREATE TABLE meeting_access_grants (
    subject_type VARCHAR(16) NOT NULL, 
    subject_id VARCHAR(64) NOT NULL, 
    actions JSONB NOT NULL, 
    scope_type VARCHAR(32) NOT NULL, 
    resource_ids JSONB NOT NULL, 
    connection_ids JSONB NOT NULL, 
    asset_types JSONB NOT NULL, 
    target_member_ids JSONB NOT NULL, 
    effect VARCHAR(8) NOT NULL, 
    purpose VARCHAR(16) NOT NULL, 
    enabled BOOLEAN NOT NULL, 
    expires_at TIMESTAMP WITH TIME ZONE, 
    issued_by VARCHAR(64) NOT NULL, 
    reason VARCHAR(500) NOT NULL, 
    org_id VARCHAR(64) NOT NULL, 
    id VARCHAR(36) NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    deleted_at TIMESTAMP WITH TIME ZONE, 
    version INTEGER NOT NULL, 
    PRIMARY KEY (id)
);

CREATE INDEX ix_meeting_access_grants_deleted_at ON meeting_access_grants (deleted_at);

CREATE INDEX ix_meeting_access_grants_org_id ON meeting_access_grants (org_id);

CREATE INDEX ix_meeting_access_grants_subject_id ON meeting_access_grants (subject_id);

CREATE TABLE meeting_applications (
    name VARCHAR(128) NOT NULL, 
    application_type VARCHAR(32) NOT NULL, 
    environment VARCHAR(16) NOT NULL, 
    tencent_corp_id VARCHAR(64) NOT NULL, 
    sdk_id VARCHAR(64) NOT NULL, 
    data_scope VARCHAR(16) NOT NULL, 
    enabled BOOLEAN NOT NULL, 
    receiver_id VARCHAR(36), 
    allowed_open_corp_ids JSONB NOT NULL, 
    webhook_verified_at TIMESTAMP WITH TIME ZONE, 
    last_callback_at TIMESTAMP WITH TIME ZONE, 
    settings_data JSONB NOT NULL, 
    org_id VARCHAR(64) NOT NULL, 
    id VARCHAR(36) NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    deleted_at TIMESTAMP WITH TIME ZONE, 
    version INTEGER NOT NULL, 
    PRIMARY KEY (id), 
    UNIQUE (receiver_id)
);

CREATE INDEX ix_meeting_applications_deleted_at ON meeting_applications (deleted_at);

CREATE INDEX ix_meeting_applications_org_id ON meeting_applications (org_id);

CREATE UNIQUE INDEX uq_meeting_app ON meeting_applications (org_id, environment, sdk_id) WHERE deleted_at IS NULL;

CREATE TABLE meeting_audit_logs (
    actor_type VARCHAR(16) NOT NULL, 
    subject_id VARCHAR(64), 
    client_id VARCHAR(36), 
    agent_id VARCHAR(128), 
    action VARCHAR(64) NOT NULL, 
    resource_id VARCHAR(128), 
    decision VARCHAR(16) NOT NULL, 
    reason VARCHAR(64), 
    trace_id VARCHAR(64) NOT NULL, 
    details JSONB NOT NULL, 
    org_id VARCHAR(64) NOT NULL, 
    id VARCHAR(36) NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    deleted_at TIMESTAMP WITH TIME ZONE, 
    version INTEGER NOT NULL, 
    PRIMARY KEY (id)
);

CREATE INDEX ix_meeting_audit_logs_deleted_at ON meeting_audit_logs (deleted_at);

CREATE INDEX ix_meeting_audit_logs_org_id ON meeting_audit_logs (org_id);

CREATE TABLE meeting_authorization_transactions (
    purpose VARCHAR(32) NOT NULL, 
    secret_hash VARCHAR(64), 
    application_id VARCHAR(36), 
    client_id VARCHAR(36), 
    member_id VARCHAR(64), 
    status VARCHAR(32) NOT NULL, 
    expires_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    used_at TIMESTAMP WITH TIME ZONE, 
    payload JSONB NOT NULL, 
    encrypted_payload TEXT, 
    org_id VARCHAR(64) NOT NULL, 
    id VARCHAR(36) NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    deleted_at TIMESTAMP WITH TIME ZONE, 
    version INTEGER NOT NULL, 
    PRIMARY KEY (id), 
    UNIQUE (secret_hash)
);

CREATE INDEX ix_meeting_authorization_transactions_deleted_at ON meeting_authorization_transactions (deleted_at);

CREATE INDEX ix_meeting_authorization_transactions_org_id ON meeting_authorization_transactions (org_id);

CREATE INDEX ix_meeting_authorization_transactions_purpose ON meeting_authorization_transactions (purpose);

CREATE TABLE meeting_clients (
    name VARCHAR(128) NOT NULL, 
    client_type VARCHAR(32) NOT NULL, 
    secret_hash VARCHAR(64), 
    allowed_scopes JSONB NOT NULL, 
    redirect_uris JSONB NOT NULL, 
    owner_member_id VARCHAR(64) NOT NULL, 
    agent_id VARCHAR(128), 
    enabled BOOLEAN NOT NULL, 
    allow_service BOOLEAN NOT NULL, 
    org_id VARCHAR(64) NOT NULL, 
    id VARCHAR(36) NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    deleted_at TIMESTAMP WITH TIME ZONE, 
    version INTEGER NOT NULL, 
    PRIMARY KEY (id)
);

CREATE INDEX ix_meeting_clients_deleted_at ON meeting_clients (deleted_at);

CREATE INDEX ix_meeting_clients_org_id ON meeting_clients (org_id);

CREATE TABLE meeting_delivered_resources (
    subscription_id VARCHAR(36) NOT NULL, 
    resource_id VARCHAR(36) NOT NULL, 
    last_delivered_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    org_id VARCHAR(64) NOT NULL, 
    id VARCHAR(36) NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    deleted_at TIMESTAMP WITH TIME ZONE, 
    version INTEGER NOT NULL, 
    PRIMARY KEY (id)
);

CREATE INDEX ix_meeting_delivered_resources_deleted_at ON meeting_delivered_resources (deleted_at);

CREATE INDEX ix_meeting_delivered_resources_org_id ON meeting_delivered_resources (org_id);

CREATE UNIQUE INDEX uq_delivered_resource ON meeting_delivered_resources (subscription_id, resource_id) WHERE deleted_at IS NULL;

CREATE TABLE meeting_download_quotas (
    client_id VARCHAR(36) NOT NULL, 
    day VARCHAR(10) NOT NULL, 
    reserved_bytes BIGINT NOT NULL, 
    completed_bytes BIGINT NOT NULL, 
    org_id VARCHAR(64) NOT NULL, 
    id VARCHAR(36) NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    deleted_at TIMESTAMP WITH TIME ZONE, 
    version INTEGER NOT NULL, 
    PRIMARY KEY (id)
);

CREATE INDEX ix_meeting_download_quotas_deleted_at ON meeting_download_quotas (deleted_at);

CREATE INDEX ix_meeting_download_quotas_org_id ON meeting_download_quotas (org_id);

CREATE UNIQUE INDEX uq_download_quota ON meeting_download_quotas (client_id, day) WHERE deleted_at IS NULL;

CREATE TABLE meeting_event_inbox (
    application_id VARCHAR(36) NOT NULL, 
    event_type VARCHAR(64) NOT NULL, 
    fingerprint VARCHAR(64) NOT NULL, 
    encrypted_payload TEXT, 
    safe_summary JSONB NOT NULL, 
    state VARCHAR(32) NOT NULL, 
    processed_at TIMESTAMP WITH TIME ZONE, 
    last_reason VARCHAR(64), 
    org_id VARCHAR(64) NOT NULL, 
    id VARCHAR(36) NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    deleted_at TIMESTAMP WITH TIME ZONE, 
    version INTEGER NOT NULL, 
    PRIMARY KEY (id)
);

CREATE INDEX ix_meeting_event_inbox_deleted_at ON meeting_event_inbox (deleted_at);

CREATE INDEX ix_meeting_event_inbox_org_id ON meeting_event_inbox (org_id);

CREATE UNIQUE INDEX uq_inbox_fingerprint ON meeting_event_inbox (fingerprint) WHERE deleted_at IS NULL;

CREATE TABLE meeting_operations (
    owner_member_id VARCHAR(64) NOT NULL, 
    client_id VARCHAR(36) NOT NULL, 
    agent_grant_id VARCHAR(36), 
    connection_id VARCHAR(36) NOT NULL, 
    host_member_id VARCHAR(64) NOT NULL, 
    idempotency_scope VARCHAR(64) NOT NULL, 
    idempotency_key_hash VARCHAR(64) NOT NULL, 
    request_hash VARCHAR(64) NOT NULL, 
    request_data JSONB NOT NULL, 
    principal_data JSONB NOT NULL, 
    operator_data JSONB NOT NULL, 
    state VARCHAR(32) NOT NULL, 
    confirm_deadline TIMESTAMP WITH TIME ZONE NOT NULL, 
    approved_by VARCHAR(64), 
    approved_at TIMESTAMP WITH TIME ZONE, 
    policy_version BIGINT NOT NULL, 
    attempt_started_at TIMESTAMP WITH TIME ZONE, 
    execution_attempt_id VARCHAR(36), 
    external_meeting_id VARCHAR(128), 
    result_meeting_id VARCHAR(36), 
    last_reason VARCHAR(64), 
    resolution_note VARCHAR(500), 
    org_id VARCHAR(64) NOT NULL, 
    id VARCHAR(36) NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    deleted_at TIMESTAMP WITH TIME ZONE, 
    version INTEGER NOT NULL, 
    PRIMARY KEY (id)
);

CREATE INDEX ix_meeting_operations_deleted_at ON meeting_operations (deleted_at);

CREATE INDEX ix_meeting_operations_org_id ON meeting_operations (org_id);

CREATE INDEX ix_meeting_operations_owner_member_id ON meeting_operations (owner_member_id);

CREATE UNIQUE INDEX uq_operation_idempotency ON meeting_operations (idempotency_scope, idempotency_key_hash) WHERE deleted_at IS NULL;

CREATE TABLE meeting_organization_policies (
    approved_by VARCHAR(64) NOT NULL, 
    retention_confirmed BOOLEAN NOT NULL, 
    metadata_days INTEGER NOT NULL, 
    content_days INTEGER NOT NULL, 
    audit_days INTEGER NOT NULL, 
    reason VARCHAR(500) NOT NULL, 
    org_id VARCHAR(64) NOT NULL, 
    id VARCHAR(36) NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    deleted_at TIMESTAMP WITH TIME ZONE, 
    version INTEGER NOT NULL, 
    PRIMARY KEY (id)
);

CREATE INDEX ix_meeting_organization_policies_deleted_at ON meeting_organization_policies (deleted_at);

CREATE INDEX ix_meeting_organization_policies_org_id ON meeting_organization_policies (org_id);

CREATE UNIQUE INDEX uq_org_policy ON meeting_organization_policies (org_id) WHERE deleted_at IS NULL;

CREATE TABLE meeting_policy_versions (
    counter BIGINT NOT NULL, 
    org_id VARCHAR(64) NOT NULL, 
    id VARCHAR(36) NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    deleted_at TIMESTAMP WITH TIME ZONE, 
    version INTEGER NOT NULL, 
    PRIMARY KEY (id)
);

CREATE INDEX ix_meeting_policy_versions_deleted_at ON meeting_policy_versions (deleted_at);

CREATE INDEX ix_meeting_policy_versions_org_id ON meeting_policy_versions (org_id);

CREATE UNIQUE INDEX uq_policy_org ON meeting_policy_versions (org_id) WHERE deleted_at IS NULL;

CREATE TABLE meeting_rate_limits (
    bucket VARCHAR(128) NOT NULL, 
    next_allowed_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    id VARCHAR(36) NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    deleted_at TIMESTAMP WITH TIME ZONE, 
    version INTEGER NOT NULL, 
    PRIMARY KEY (id)
);

CREATE INDEX ix_meeting_rate_limits_deleted_at ON meeting_rate_limits (deleted_at);

CREATE UNIQUE INDEX uq_rate_bucket ON meeting_rate_limits (bucket) WHERE deleted_at IS NULL;

CREATE TABLE meeting_resource_acl (
    resource_type VARCHAR(16) NOT NULL, 
    resource_id VARCHAR(36) NOT NULL, 
    subject_type VARCHAR(16) NOT NULL, 
    subject_id VARCHAR(64) NOT NULL, 
    effect VARCHAR(8) NOT NULL, 
    actions JSONB NOT NULL, 
    asset_types JSONB NOT NULL, 
    expires_at TIMESTAMP WITH TIME ZONE, 
    issued_by VARCHAR(64) NOT NULL, 
    reason VARCHAR(500) NOT NULL, 
    org_id VARCHAR(64) NOT NULL, 
    id VARCHAR(36) NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    deleted_at TIMESTAMP WITH TIME ZONE, 
    version INTEGER NOT NULL, 
    PRIMARY KEY (id)
);

CREATE INDEX ix_meeting_resource_acl_deleted_at ON meeting_resource_acl (deleted_at);

CREATE INDEX ix_meeting_resource_acl_org_id ON meeting_resource_acl (org_id);

CREATE INDEX ix_meeting_resource_acl_resource_id ON meeting_resource_acl (resource_id);

CREATE TABLE meeting_sync_jobs (
    kind VARCHAR(32) NOT NULL, 
    connection_id VARCHAR(36), 
    owner_member_id VARCHAR(64), 
    client_id VARCHAR(36) NOT NULL, 
    agent_grant_id VARCHAR(36), 
    ingestion_grant_id VARCHAR(36), 
    principal_data JSONB NOT NULL, 
    payload JSONB NOT NULL, 
    progress JSONB NOT NULL, 
    dedup_key VARCHAR(128), 
    state VARCHAR(32) NOT NULL, 
    attempts INTEGER NOT NULL, 
    run_after TIMESTAMP WITH TIME ZONE NOT NULL, 
    lease_until TIMESTAMP WITH TIME ZONE, 
    lease_owner VARCHAR(64), 
    lease_token VARCHAR(36), 
    last_reason VARCHAR(64), 
    org_id VARCHAR(64) NOT NULL, 
    id VARCHAR(36) NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    deleted_at TIMESTAMP WITH TIME ZONE, 
    version INTEGER NOT NULL, 
    PRIMARY KEY (id)
);

CREATE INDEX ix_job_ready ON meeting_sync_jobs (state, run_after);

CREATE INDEX ix_meeting_sync_jobs_deleted_at ON meeting_sync_jobs (deleted_at);

CREATE INDEX ix_meeting_sync_jobs_org_id ON meeting_sync_jobs (org_id);

CREATE UNIQUE INDEX uq_job_dedup ON meeting_sync_jobs (dedup_key) WHERE deleted_at IS NULL;

CREATE TABLE meeting_sync_policies (
    connection_id VARCHAR(36) NOT NULL, 
    client_id VARCHAR(36) NOT NULL, 
    ingestion_grant_id VARCHAR(36) NOT NULL, 
    interval_seconds INTEGER NOT NULL, 
    overlap_seconds INTEGER NOT NULL, 
    next_run_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    last_success_at TIMESTAMP WITH TIME ZONE, 
    enabled BOOLEAN NOT NULL, 
    org_id VARCHAR(64) NOT NULL, 
    id VARCHAR(36) NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    deleted_at TIMESTAMP WITH TIME ZONE, 
    version INTEGER NOT NULL, 
    PRIMARY KEY (id)
);

CREATE INDEX ix_meeting_sync_policies_deleted_at ON meeting_sync_policies (deleted_at);

CREATE INDEX ix_meeting_sync_policies_org_id ON meeting_sync_policies (org_id);

CREATE TABLE meeting_agent_grants (
    member_id VARCHAR(64) NOT NULL, 
    client_id VARCHAR(36) NOT NULL, 
    agent_id VARCHAR(128) NOT NULL, 
    actions JSONB NOT NULL, 
    scope_type VARCHAR(32) NOT NULL, 
    resource_ids JSONB NOT NULL, 
    connection_ids JSONB NOT NULL, 
    asset_types JSONB NOT NULL, 
    target_member_ids JSONB NOT NULL, 
    effect VARCHAR(8) NOT NULL, 
    purpose VARCHAR(16) NOT NULL, 
    enabled BOOLEAN NOT NULL, 
    expires_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    issued_by VARCHAR(64) NOT NULL, 
    confirmation_required BOOLEAN NOT NULL, 
    reason VARCHAR(500) NOT NULL, 
    org_id VARCHAR(64) NOT NULL, 
    id VARCHAR(36) NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    deleted_at TIMESTAMP WITH TIME ZONE, 
    version INTEGER NOT NULL, 
    PRIMARY KEY (id), 
    FOREIGN KEY(client_id) REFERENCES meeting_clients (id)
);

CREATE INDEX ix_meeting_agent_grants_deleted_at ON meeting_agent_grants (deleted_at);

CREATE INDEX ix_meeting_agent_grants_member_id ON meeting_agent_grants (member_id);

CREATE INDEX ix_meeting_agent_grants_org_id ON meeting_agent_grants (org_id);

CREATE TABLE meeting_connections (
    application_id VARCHAR(36) NOT NULL, 
    kind VARCHAR(32) NOT NULL, 
    member_id VARCHAR(64), 
    external_id VARCHAR(128) NOT NULL, 
    external_corp_id VARCHAR(128), 
    corporate_verified BOOLEAN NOT NULL, 
    status VARCHAR(32) NOT NULL, 
    scopes JSONB NOT NULL, 
    capabilities JSONB NOT NULL, 
    last_verified_at TIMESTAMP WITH TIME ZONE, 
    last_reason VARCHAR(64), 
    last_synced_at TIMESTAMP WITH TIME ZONE, 
    sync_coverage JSONB NOT NULL, 
    consent_confirmed_at TIMESTAMP WITH TIME ZONE, 
    source_health_at TIMESTAMP WITH TIME ZONE, 
    settings_data JSONB NOT NULL, 
    org_id VARCHAR(64) NOT NULL, 
    id VARCHAR(36) NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    deleted_at TIMESTAMP WITH TIME ZONE, 
    version INTEGER NOT NULL, 
    PRIMARY KEY (id), 
    FOREIGN KEY(application_id) REFERENCES meeting_applications (id)
);

CREATE INDEX ix_meeting_connections_application_id ON meeting_connections (application_id);

CREATE INDEX ix_meeting_connections_deleted_at ON meeting_connections (deleted_at);

CREATE INDEX ix_meeting_connections_member_id ON meeting_connections (member_id);

CREATE INDEX ix_meeting_connections_org_id ON meeting_connections (org_id);

CREATE UNIQUE INDEX uq_connection_identity ON meeting_connections (org_id, application_id, external_id) WHERE deleted_at IS NULL;

CREATE TABLE meeting_credentials (
    application_id VARCHAR(36) NOT NULL, 
    connection_id VARCHAR(36), 
    purpose VARCHAR(32) NOT NULL, 
    ciphertext TEXT NOT NULL, 
    key_id VARCHAR(64) NOT NULL, 
    expires_at TIMESTAMP WITH TIME ZONE, 
    generation BIGINT NOT NULL, 
    active BOOLEAN NOT NULL, 
    org_id VARCHAR(64) NOT NULL, 
    id VARCHAR(36) NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    deleted_at TIMESTAMP WITH TIME ZONE, 
    version INTEGER NOT NULL, 
    PRIMARY KEY (id), 
    FOREIGN KEY(application_id) REFERENCES meeting_applications (id)
);

CREATE INDEX ix_meeting_credentials_application_id ON meeting_credentials (application_id);

CREATE INDEX ix_meeting_credentials_connection_id ON meeting_credentials (connection_id);

CREATE INDEX ix_meeting_credentials_deleted_at ON meeting_credentials (deleted_at);

CREATE INDEX ix_meeting_credentials_org_id ON meeting_credentials (org_id);

CREATE INDEX ix_meeting_credentials_purpose ON meeting_credentials (purpose);

CREATE TABLE meeting_event_subscriptions (
    client_id VARCHAR(36) NOT NULL, 
    destination VARCHAR(1024) NOT NULL, 
    secret_ciphertext TEXT NOT NULL, 
    event_types JSONB NOT NULL, 
    member_id VARCHAR(64), 
    agent_grant_id VARCHAR(36), 
    enabled BOOLEAN NOT NULL, 
    org_id VARCHAR(64) NOT NULL, 
    id VARCHAR(36) NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    deleted_at TIMESTAMP WITH TIME ZONE, 
    version INTEGER NOT NULL, 
    PRIMARY KEY (id), 
    FOREIGN KEY(client_id) REFERENCES meeting_clients (id)
);

CREATE INDEX ix_meeting_event_subscriptions_deleted_at ON meeting_event_subscriptions (deleted_at);

CREATE INDEX ix_meeting_event_subscriptions_org_id ON meeting_event_subscriptions (org_id);

CREATE TABLE meeting_identity_bindings (
    application_id VARCHAR(36) NOT NULL, 
    member_id VARCHAR(64) NOT NULL, 
    identity_type VARCHAR(16) NOT NULL, 
    external_id VARCHAR(128) NOT NULL, 
    external_corp_id VARCHAR(128) NOT NULL, 
    verification_source VARCHAR(500) NOT NULL, 
    verified_by VARCHAR(64) NOT NULL, 
    verified_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    enabled BOOLEAN NOT NULL, 
    org_id VARCHAR(64) NOT NULL, 
    id VARCHAR(36) NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    deleted_at TIMESTAMP WITH TIME ZONE, 
    version INTEGER NOT NULL, 
    PRIMARY KEY (id), 
    FOREIGN KEY(application_id) REFERENCES meeting_applications (id)
);

CREATE INDEX ix_meeting_identity_bindings_deleted_at ON meeting_identity_bindings (deleted_at);

CREATE INDEX ix_meeting_identity_bindings_member_id ON meeting_identity_bindings (member_id);

CREATE INDEX ix_meeting_identity_bindings_org_id ON meeting_identity_bindings (org_id);

CREATE UNIQUE INDEX uq_binding_external ON meeting_identity_bindings (org_id, application_id, identity_type, external_id) WHERE deleted_at IS NULL;

CREATE UNIQUE INDEX uq_binding_member ON meeting_identity_bindings (org_id, application_id, identity_type, member_id) WHERE deleted_at IS NULL;

CREATE TABLE meeting_sts_callbacks (
    application_id VARCHAR(36) NOT NULL, 
    req_id VARCHAR(128) NOT NULL, 
    token_ciphertext TEXT NOT NULL, 
    expires_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    operator_id VARCHAR(128), 
    operate_time_ms BIGINT NOT NULL, 
    associated_request_id VARCHAR(36), 
    org_id VARCHAR(64) NOT NULL, 
    id VARCHAR(36) NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    deleted_at TIMESTAMP WITH TIME ZONE, 
    version INTEGER NOT NULL, 
    PRIMARY KEY (id), 
    FOREIGN KEY(application_id) REFERENCES meeting_applications (id)
);

CREATE INDEX ix_meeting_sts_callbacks_deleted_at ON meeting_sts_callbacks (deleted_at);

CREATE INDEX ix_meeting_sts_callbacks_org_id ON meeting_sts_callbacks (org_id);

CREATE UNIQUE INDEX uq_sts_callback_req ON meeting_sts_callbacks (application_id, req_id) WHERE deleted_at IS NULL;

CREATE TABLE meeting_access_tokens (
    token_hash VARCHAR(64) NOT NULL, 
    refresh_hash VARCHAR(64), 
    family_id VARCHAR(36) NOT NULL, 
    client_id VARCHAR(36) NOT NULL, 
    actor_type VARCHAR(16) NOT NULL, 
    member_id VARCHAR(64), 
    user_id VARCHAR(64), 
    agent_id VARCHAR(128), 
    agent_grant_id VARCHAR(36), 
    audience VARCHAR(512) NOT NULL, 
    scopes JSONB NOT NULL, 
    expires_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    refresh_expires_at TIMESTAMP WITH TIME ZONE, 
    refresh_used_at TIMESTAMP WITH TIME ZONE, 
    revoked_at TIMESTAMP WITH TIME ZONE, 
    org_id VARCHAR(64) NOT NULL, 
    id VARCHAR(36) NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    deleted_at TIMESTAMP WITH TIME ZONE, 
    version INTEGER NOT NULL, 
    PRIMARY KEY (id), 
    FOREIGN KEY(agent_grant_id) REFERENCES meeting_agent_grants (id), 
    FOREIGN KEY(client_id) REFERENCES meeting_clients (id), 
    UNIQUE (refresh_hash), 
    UNIQUE (token_hash)
);

CREATE INDEX ix_meeting_access_tokens_client_id ON meeting_access_tokens (client_id);

CREATE INDEX ix_meeting_access_tokens_deleted_at ON meeting_access_tokens (deleted_at);

CREATE INDEX ix_meeting_access_tokens_family_id ON meeting_access_tokens (family_id);

CREATE INDEX ix_meeting_access_tokens_org_id ON meeting_access_tokens (org_id);

CREATE TABLE meeting_event_outbox (
    event_id VARCHAR(36) NOT NULL, 
    subscription_id VARCHAR(36) NOT NULL, 
    event_type VARCHAR(64) NOT NULL, 
    resource_id VARCHAR(36), 
    payload JSONB NOT NULL, 
    state VARCHAR(32) NOT NULL, 
    attempts INTEGER NOT NULL, 
    run_after TIMESTAMP WITH TIME ZONE NOT NULL, 
    delivered_at TIMESTAMP WITH TIME ZONE, 
    last_reason VARCHAR(64), 
    org_id VARCHAR(64) NOT NULL, 
    id VARCHAR(36) NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    deleted_at TIMESTAMP WITH TIME ZONE, 
    version INTEGER NOT NULL, 
    PRIMARY KEY (id), 
    FOREIGN KEY(subscription_id) REFERENCES meeting_event_subscriptions (id)
);

CREATE INDEX ix_meeting_event_outbox_deleted_at ON meeting_event_outbox (deleted_at);

CREATE INDEX ix_meeting_event_outbox_org_id ON meeting_event_outbox (org_id);

CREATE UNIQUE INDEX uq_outbox_delivery ON meeting_event_outbox (event_id, subscription_id) WHERE deleted_at IS NULL;

CREATE TABLE meeting_sts_requests (
    application_id VARCHAR(36) NOT NULL, 
    connection_id VARCHAR(36) NOT NULL, 
    req_id VARCHAR(128), 
    requested_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    valid_hours INTEGER NOT NULL, 
    status VARCHAR(32) NOT NULL, 
    generation BIGINT NOT NULL, 
    org_id VARCHAR(64) NOT NULL, 
    id VARCHAR(36) NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    deleted_at TIMESTAMP WITH TIME ZONE, 
    version INTEGER NOT NULL, 
    PRIMARY KEY (id), 
    FOREIGN KEY(application_id) REFERENCES meeting_applications (id), 
    FOREIGN KEY(connection_id) REFERENCES meeting_connections (id)
);

CREATE INDEX ix_meeting_sts_requests_application_id ON meeting_sts_requests (application_id);

CREATE INDEX ix_meeting_sts_requests_deleted_at ON meeting_sts_requests (deleted_at);

CREATE INDEX ix_meeting_sts_requests_org_id ON meeting_sts_requests (org_id);

CREATE INDEX ix_meeting_sts_requests_req_id ON meeting_sts_requests (req_id);

CREATE TABLE meetings (
    connection_id VARCHAR(36) NOT NULL, 
    external_namespace VARCHAR(128) NOT NULL, 
    external_id VARCHAR(128) NOT NULL, 
    subject VARCHAR(512) NOT NULL, 
    meeting_code VARCHAR(64), 
    created_by_member_id VARCHAR(64), 
    host_member_id VARCHAR(64), 
    start_at TIMESTAMP WITH TIME ZONE, 
    end_at TIMESTAMP WITH TIME ZONE, 
    state VARCHAR(32) NOT NULL, 
    synced_at TIMESTAMP WITH TIME ZONE, 
    source_time_ms BIGINT NOT NULL, 
    org_id VARCHAR(64) NOT NULL, 
    id VARCHAR(36) NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    deleted_at TIMESTAMP WITH TIME ZONE, 
    version INTEGER NOT NULL, 
    PRIMARY KEY (id), 
    FOREIGN KEY(connection_id) REFERENCES meeting_connections (id)
);

CREATE INDEX ix_meetings_connection_id ON meetings (connection_id);

CREATE INDEX ix_meetings_created_by_member_id ON meetings (created_by_member_id);

CREATE INDEX ix_meetings_deleted_at ON meetings (deleted_at);

CREATE INDEX ix_meetings_host_member_id ON meetings (host_member_id);

CREATE INDEX ix_meetings_org_id ON meetings (org_id);

CREATE UNIQUE INDEX uq_meeting_namespace ON meetings (org_id, external_namespace, external_id) WHERE deleted_at IS NULL;

CREATE TABLE meeting_participants (
    meeting_id VARCHAR(36) NOT NULL, 
    member_id VARCHAR(64) NOT NULL, 
    verified BOOLEAN NOT NULL, 
    source VARCHAR(32) NOT NULL, 
    org_id VARCHAR(64) NOT NULL, 
    id VARCHAR(36) NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    deleted_at TIMESTAMP WITH TIME ZONE, 
    version INTEGER NOT NULL, 
    PRIMARY KEY (id), 
    FOREIGN KEY(meeting_id) REFERENCES meetings (id)
);

CREATE INDEX ix_meeting_participants_deleted_at ON meeting_participants (deleted_at);

CREATE INDEX ix_meeting_participants_meeting_id ON meeting_participants (meeting_id);

CREATE INDEX ix_meeting_participants_org_id ON meeting_participants (org_id);

CREATE UNIQUE INDEX uq_meeting_participant ON meeting_participants (meeting_id, member_id) WHERE deleted_at IS NULL;

CREATE TABLE meeting_recordings (
    meeting_id VARCHAR(36) NOT NULL, 
    connection_id VARCHAR(36) NOT NULL, 
    external_file_id VARCHAR(128) NOT NULL, 
    external_record_id VARCHAR(128), 
    recording_group_id VARCHAR(128) NOT NULL, 
    start_at TIMESTAMP WITH TIME ZONE, 
    end_at TIMESTAMP WITH TIME ZONE, 
    size_bytes BIGINT, 
    state VARCHAR(32) NOT NULL, 
    synced_at TIMESTAMP WITH TIME ZONE, 
    org_id VARCHAR(64) NOT NULL, 
    id VARCHAR(36) NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    deleted_at TIMESTAMP WITH TIME ZONE, 
    version INTEGER NOT NULL, 
    PRIMARY KEY (id), 
    FOREIGN KEY(connection_id) REFERENCES meeting_connections (id), 
    FOREIGN KEY(meeting_id) REFERENCES meetings (id)
);

CREATE INDEX ix_meeting_recordings_deleted_at ON meeting_recordings (deleted_at);

CREATE INDEX ix_meeting_recordings_meeting_id ON meeting_recordings (meeting_id);

CREATE INDEX ix_meeting_recordings_org_id ON meeting_recordings (org_id);

CREATE UNIQUE INDEX uq_record_file ON meeting_recordings (org_id, connection_id, external_file_id) WHERE deleted_at IS NULL;

CREATE TABLE meeting_resource_origins (
    meeting_id VARCHAR(36) NOT NULL, 
    recording_id VARCHAR(36), 
    asset_id VARCHAR(36), 
    connection_id VARCHAR(36) NOT NULL, 
    purpose VARCHAR(16) NOT NULL, 
    ingestion_grant_id VARCHAR(36), 
    owner_member_id VARCHAR(64), 
    enabled BOOLEAN NOT NULL, 
    last_verified_at TIMESTAMP WITH TIME ZONE, 
    last_reason VARCHAR(64), 
    org_id VARCHAR(64) NOT NULL, 
    id VARCHAR(36) NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    deleted_at TIMESTAMP WITH TIME ZONE, 
    version INTEGER NOT NULL, 
    PRIMARY KEY (id), 
    FOREIGN KEY(connection_id) REFERENCES meeting_connections (id), 
    FOREIGN KEY(ingestion_grant_id) REFERENCES meeting_access_grants (id), 
    FOREIGN KEY(meeting_id) REFERENCES meetings (id)
);

CREATE INDEX ix_meeting_resource_origins_asset_id ON meeting_resource_origins (asset_id);

CREATE INDEX ix_meeting_resource_origins_deleted_at ON meeting_resource_origins (deleted_at);

CREATE INDEX ix_meeting_resource_origins_meeting_id ON meeting_resource_origins (meeting_id);

CREATE INDEX ix_meeting_resource_origins_org_id ON meeting_resource_origins (org_id);

CREATE TABLE meeting_assets (
    meeting_id VARCHAR(36) NOT NULL, 
    recording_id VARCHAR(36) NOT NULL, 
    connection_id VARCHAR(36) NOT NULL, 
    asset_type VARCHAR(16) NOT NULL, 
    content_hash VARCHAR(64) NOT NULL, 
    state VARCHAR(32) NOT NULL, 
    is_complete BOOLEAN NOT NULL, 
    object_key VARCHAR(256), 
    content_type VARCHAR(128) NOT NULL, 
    details JSONB NOT NULL, 
    fetched_at TIMESTAMP WITH TIME ZONE, 
    expires_at TIMESTAMP WITH TIME ZONE, 
    source_health_at TIMESTAMP WITH TIME ZONE, 
    org_id VARCHAR(64) NOT NULL, 
    id VARCHAR(36) NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    deleted_at TIMESTAMP WITH TIME ZONE, 
    version INTEGER NOT NULL, 
    PRIMARY KEY (id), 
    FOREIGN KEY(connection_id) REFERENCES meeting_connections (id), 
    FOREIGN KEY(meeting_id) REFERENCES meetings (id), 
    FOREIGN KEY(recording_id) REFERENCES meeting_recordings (id)
);

CREATE INDEX ix_meeting_assets_deleted_at ON meeting_assets (deleted_at);

CREATE INDEX ix_meeting_assets_meeting_id ON meeting_assets (meeting_id);

CREATE INDEX ix_meeting_assets_org_id ON meeting_assets (org_id);

CREATE INDEX ix_meeting_assets_recording_id ON meeting_assets (recording_id);

CREATE UNIQUE INDEX uq_asset_version ON meeting_assets (recording_id, asset_type, content_hash) WHERE deleted_at IS NULL;

CREATE TABLE meeting_download_tickets (
    token_hash VARCHAR(64) NOT NULL, 
    principal_binding VARCHAR(64) NOT NULL, 
    principal_data JSONB NOT NULL, 
    asset_id VARCHAR(36) NOT NULL, 
    asset_version VARCHAR(64) NOT NULL, 
    purpose VARCHAR(128) NOT NULL, 
    expires_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    session_expires_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    started_at TIMESTAMP WITH TIME ZONE, 
    bytes_sent BIGINT NOT NULL, 
    active_streams INTEGER NOT NULL, 
    stream_lease_at TIMESTAMP WITH TIME ZONE, 
    revoked_at TIMESTAMP WITH TIME ZONE, 
    org_id VARCHAR(64) NOT NULL, 
    id VARCHAR(36) NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    deleted_at TIMESTAMP WITH TIME ZONE, 
    version INTEGER NOT NULL, 
    PRIMARY KEY (id), 
    FOREIGN KEY(asset_id) REFERENCES meeting_assets (id), 
    UNIQUE (token_hash)
);

CREATE INDEX ix_meeting_download_tickets_deleted_at ON meeting_download_tickets (deleted_at);

CREATE INDEX ix_meeting_download_tickets_org_id ON meeting_download_tickets (org_id);

INSERT INTO alembic_version (version_num) VALUES ('1d4f7c955b82') RETURNING alembic_version.version_num;

COMMIT;

