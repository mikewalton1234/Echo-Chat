#!/usr/bin/env python3
"""
Echo-Chat server – database facade helpers (PostgreSQL version)

This module remains the compatibility facade while connection, migration,
auth, room, and schema/bootstrap helpers now live in the ``db/`` package.
Existing imports from ``database.py`` continue to work.
"""

from constants import get_db_connection_string, sanitize_postgres_dsn, redact_postgres_dsn, postgres_dsn_parts
from db.shared import JSON_ROOMS_PATH, MIGRATIONS_DIR, SCHEMA_META_TABLE, MigrationSpec
from db.core import init_db_pool, _acquire_conn, _release_conn, get_db, close_db, init_database, get_db_identity, get_schema_version, init_app
from db.migrations import _ensure_schema_meta_table, _checksum_path, _load_python_migration, list_available_migrations, _get_applied_migration_rows, apply_migrations
from db.rooms import _read_rooms_json, _official_room_names_from_data, _official_room_names_from_json, get_blocked_users, get_pending_friend_requests, load_rooms_from_json, consume_room_invites, set_room_message_expiry, get_room_message_expiry, cleanup_expired_room_messages, is_user_verified, get_custom_room_meta, record_custom_room_membership, get_custom_room_user_role, can_user_moderate_custom_room, custom_room_role_rank, revoke_custom_room_access, can_user_access_custom_room, can_user_join_custom_room, touch_custom_room_activity, cleanup_expired_custom_rooms, delete_custom_room_persisted_state, get_friends_for_user, get_all_rooms, create_room_if_missing, create_autoscaled_room_if_missing, increment_room_count, cleanup_expired_autoscaled_rooms, dump_tables, seed_rooms_from_file
from db.auth import (
    _pbkdf2_key,
    _encrypt_private_key_v2,
    _decrypt_private_key_blob,
    _generate_and_encrypt_rsa_keypair,
    generate_user_keypair_for_password,
    create_user_with_keys,
    ensure_user_has_default_avatar,
    canonical_username,
    find_user_by_username_ci,
    get_auth_version,
    bump_auth_version,
    create_auth_session_in_conn,
    create_login_session_and_tokens,
    store_auth_token_in_conn,
    rotate_refresh_and_store_access_token,
    get_public_key_for_username,
    user_exists,
    email_in_use,
    ensure_user_has_keys,
    get_encrypted_private_key_for_username,
    store_auth_token,
    revoke_auth_token,
    revoke_all_tokens_for_user,
    is_auth_token_revoked,
    create_auth_session,
    touch_auth_session,
    touch_auth_session_activity,
    is_auth_session_active,
    get_auth_session_state,
    get_session_id_for_token,
    attach_session_to_token,
    revoke_auth_session,
    revoke_other_sessions_for_user,
    revoke_all_sessions_for_user,
    revoke_all_sessions_and_tokens_for_user,
    apply_auth_risk_event,
    list_auth_sessions,
    revoke_all_tokens_global,
    is_refresh_token_active,
    get_refresh_token_meta,
    is_refresh_token_usable,
    rotate_refresh_token,
    touch_auth_token,
)
from db.schema import _log_table_owner_mismatch, ensure_online_column, ensure_presence_columns, ensure_users_profile_columns, ensure_profile_post_engagement_schema, ensure_chat_rooms_table, sync_chat_room_kinds, ensure_users_key_columns, ensure_users_security_columns, ensure_account_recovery_schema, ensure_auth_session_schema, ensure_user_verified_column, ensure_custom_rooms_schema, ensure_room_message_expiry_schema, _create_full_schema, _seed_roles_permissions, _legacy_bootstrap_schema
