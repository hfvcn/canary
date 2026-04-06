import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from cccc.daemon.group.bootstrap_actor_ops import autostart_running_groups


class TestBootstrapActorOps(unittest.TestCase):
    def _with_home(self):
        old_home = os.environ.get("CCCC_HOME")
        td_ctx = tempfile.TemporaryDirectory()
        td = td_ctx.__enter__()
        os.environ["CCCC_HOME"] = td

        def cleanup() -> None:
            td_ctx.__exit__(None, None, None)
            if old_home is None:
                os.environ.pop("CCCC_HOME", None)
            else:
                os.environ["CCCC_HOME"] = old_home

        return Path(td), cleanup

    def _call(self, op: str, args: dict):
        from cccc.contracts.v1 import DaemonRequest
        from cccc.daemon.server import handle_request

        return handle_request(DaemonRequest.model_validate({"op": op, "args": args}))

    def test_server_autostart_passes_caller_context_to_profile_resolver(self) -> None:
        from cccc.daemon import server as daemon_server

        captured: dict[str, object] = {}

        def _fake_autostart_running_groups(_home: Path, **kwargs):
            resolver = kwargs["resolve_linked_actor_before_start"]
            captured["resolved"] = resolver("group", "actor", caller_id="user-a", is_admin=False)

        with patch.object(daemon_server, "autostart_running_groups", side_effect=_fake_autostart_running_groups), patch.object(
            daemon_server,
            "_resolve_linked_actor_before_start",
            return_value={"id": "actor", "profile_owner": "user-a"},
        ) as resolve_mock:
            daemon_server._maybe_autostart_running_groups()

        self.assertEqual(captured["resolved"], {"id": "actor", "profile_owner": "user-a"})
        resolve_mock.assert_called_once()
        self.assertEqual(resolve_mock.call_args.kwargs["caller_id"], "user-a")
        self.assertFalse(bool(resolve_mock.call_args.kwargs["is_admin"]))

    def test_no_groups_is_noop(self) -> None:
        home, cleanup = self._with_home()
        try:
            autostart_running_groups(
                home,
                effective_runner_kind=lambda runner: runner,
                find_scope_url=lambda _group, _scope_key: "",
                supported_runtimes=("codex",),
                ensure_mcp_installed=lambda _runtime, _cwd: True,
                auto_mcp_runtimes=("codex",),
                pty_supported=lambda: True,
                merge_actor_env_with_private=lambda _gid, _aid, env: dict(env),
                inject_actor_context_env=lambda env, _gid, _aid: dict(env),
                prepare_pty_env=lambda env: dict(env),
                normalize_runtime_command=lambda _runtime, command: list(command),
                pty_backlog_bytes=lambda: 1024,
                write_headless_state=lambda _gid, _aid: None,
                write_pty_state=lambda _gid, _aid, _pid: None,
                clear_preamble_sent=lambda _group, _aid: None,
                throttle_reset_actor=lambda _gid, _aid: None,
                automation_on_resume=lambda _group: None,
                get_group_state=lambda _group: "idle",
            )
        finally:
            cleanup()

    def test_running_group_without_active_scope_is_cleared(self) -> None:
        home, cleanup = self._with_home()
        try:
            create, _ = self._call("group_create", {"title": "autostart", "topic": "", "by": "user"})
            self.assertTrue(create.ok, getattr(create, "error", None))
            group_id = str((create.result or {}).get("group_id") or "").strip()
            self.assertTrue(group_id)

            from cccc.kernel.group import load_group

            group = load_group(group_id)
            self.assertIsNotNone(group)
            assert group is not None
            group.doc["running"] = True
            group.doc["active_scope_key"] = ""
            group.save()

            autostart_running_groups(
                home,
                effective_runner_kind=lambda runner: runner,
                find_scope_url=lambda _group, _scope_key: "",
                supported_runtimes=("codex",),
                ensure_mcp_installed=lambda _runtime, _cwd: True,
                auto_mcp_runtimes=("codex",),
                pty_supported=lambda: True,
                merge_actor_env_with_private=lambda _gid, _aid, env: dict(env),
                inject_actor_context_env=lambda env, _gid, _aid: dict(env),
                prepare_pty_env=lambda env: dict(env),
                normalize_runtime_command=lambda _runtime, command: list(command),
                pty_backlog_bytes=lambda: 1024,
                write_headless_state=lambda _gid, _aid: None,
                write_pty_state=lambda _gid, _aid, _pid: None,
                clear_preamble_sent=lambda _group, _aid: None,
                throttle_reset_actor=lambda _gid, _aid: None,
                automation_on_resume=lambda _group: None,
                get_group_state=lambda _group: "idle",
            )

            reloaded = load_group(group_id)
            self.assertIsNotNone(reloaded)
            assert reloaded is not None
            self.assertFalse(bool(reloaded.doc.get("running")))
        finally:
            cleanup()

    def test_autostart_restores_explicit_user_scope_profile_secrets(self) -> None:
        home, cleanup = self._with_home()
        try:
            from cccc.daemon.actors.actor_profile_runtime import resolve_linked_actor_before_start
            from cccc.daemon.actors.actor_profile_store import get_actor_profile, load_actor_profile_secrets
            from cccc.daemon.actors.private_env_ops import merge_actor_env_with_private, update_actor_private_env
            from cccc.kernel.actors import find_actor
            from cccc.kernel.group import load_group

            create, _ = self._call("group_create", {"title": "autostart-profile", "topic": "", "by": "user"})
            self.assertTrue(create.ok, getattr(create, "error", None))
            group_id = str((create.result or {}).get("group_id") or "").strip()
            self.assertTrue(group_id)

            profile_upsert, _ = self._call(
                "actor_profile_upsert",
                {
                    "by": "user",
                    "caller_id": "user-a",
                    "is_admin": False,
                    "profile": {
                        "id": "member-profile",
                        "name": "Member Profile",
                        "scope": "user",
                        "owner_id": "user-a",
                        "runtime": "custom",
                        "runner": "headless",
                        "command": [],
                        "submit": "newline",
                    },
                },
            )
            self.assertTrue(profile_upsert.ok, getattr(profile_upsert, "error", None))

            secret_update, _ = self._call(
                "actor_profile_secret_update",
                {
                    "by": "user",
                    "profile_id": "member-profile",
                    "profile_scope": "user",
                    "profile_owner": "user-a",
                    "caller_id": "user-a",
                    "is_admin": False,
                    "set": {"API_KEY": "user-secret"},
                },
            )
            self.assertTrue(secret_update.ok, getattr(secret_update, "error", None))

            attach, _ = self._call("attach", {"group_id": group_id, "path": ".", "by": "user"})
            self.assertTrue(attach.ok, getattr(attach, "error", None))

            add, _ = self._call(
                "actor_add",
                {
                    "group_id": group_id,
                    "actor_id": "peer1",
                    "runtime": "codex",
                    "runner": "headless",
                    "profile_id": "member-profile",
                    "profile_scope": "user",
                    "profile_owner": "user-a",
                    "caller_id": "user-a",
                    "is_admin": False,
                    "by": "user",
                },
            )
            self.assertTrue(add.ok, getattr(add, "error", None))

            group = load_group(group_id)
            self.assertIsNotNone(group)
            assert group is not None
            group.doc["running"] = True
            group.save()

            captured: list[dict[str, object]] = []

            def _fake_headless_start_actor(*, group_id: str, actor_id: str, cwd: Path, env: dict[str, str]):
                captured.append(
                    {
                        "group_id": group_id,
                        "actor_id": actor_id,
                        "cwd": cwd,
                        "env": dict(env),
                    }
                )

                class _Session:
                    pass

                return _Session()

            with patch("cccc.daemon.group.bootstrap_actor_ops.headless_runner.SUPERVISOR.start_actor", side_effect=_fake_headless_start_actor):
                autostart_running_groups(
                    home,
                    effective_runner_kind=lambda runner: runner,
                    find_scope_url=lambda current_group, scope_key: (
                        str(Path(".").resolve())
                        if str(current_group.group_id or "").strip() == group_id and str(scope_key or "").strip()
                        else ""
                    ),
                    supported_runtimes=("codex", "custom"),
                    ensure_mcp_installed=lambda _runtime, _cwd: True,
                    auto_mcp_runtimes=("codex",),
                    pty_supported=lambda: True,
                    merge_actor_env_with_private=merge_actor_env_with_private,
                    inject_actor_context_env=lambda env, _gid, _aid: dict(env),
                    prepare_pty_env=lambda env: dict(env),
                    normalize_runtime_command=lambda _runtime, command: list(command),
                    pty_backlog_bytes=lambda: 1024,
                    write_headless_state=lambda _gid, _aid: None,
                    write_pty_state=lambda _gid, _aid, _pid: None,
                    clear_preamble_sent=lambda _group, _aid: None,
                    throttle_reset_actor=lambda _gid, _aid: None,
                    automation_on_resume=lambda _group: None,
                    get_group_state=lambda _group: "idle",
                    resolve_linked_actor_before_start=lambda grp, aid, caller_id="", is_admin=False: resolve_linked_actor_before_start(
                        grp,
                        aid,
                        get_actor_profile=get_actor_profile,
                        load_actor_profile_secrets=load_actor_profile_secrets,
                        update_actor_private_env=update_actor_private_env,
                        caller_id=caller_id,
                        is_admin=is_admin,
                    ),
                )

            self.assertEqual(len(captured), 1)
            launched = captured[0]
            self.assertEqual(launched.get("group_id"), group_id)
            self.assertEqual(launched.get("actor_id"), "peer1")
            env = launched.get("env")
            self.assertIsInstance(env, dict)
            assert isinstance(env, dict)
            self.assertEqual(env.get("API_KEY"), "user-secret")

            reloaded = load_group(group_id)
            self.assertIsNotNone(reloaded)
            assert reloaded is not None
            actor = find_actor(reloaded, "peer1")
            self.assertIsNotNone(actor)
            assert actor is not None
            self.assertEqual(str(actor.get("runtime") or ""), "custom")
            self.assertEqual(str(actor.get("submit") or ""), "newline")
            self.assertEqual(str(actor.get("profile_scope") or ""), "user")
            self.assertEqual(str(actor.get("profile_owner") or ""), "user-a")
        finally:
            cleanup()


    def test_global_profile_start_persists_explicit_scope(self) -> None:
        """Global profile attach persists profile_scope='global' and start resolves via explicit ref."""
        home, cleanup = self._with_home()
        try:
            from cccc.daemon.actors.actor_profile_runtime import resolve_linked_actor_before_start
            from cccc.daemon.actors.actor_profile_store import get_actor_profile, load_actor_profile_secrets
            from cccc.daemon.actors.private_env_ops import update_actor_private_env
            from cccc.kernel.actors import find_actor
            from cccc.kernel.group import load_group

            create, _ = self._call("group_create", {"title": "global-start", "topic": "", "by": "user"})
            self.assertTrue(create.ok, getattr(create, "error", None))
            group_id = str((create.result or {}).get("group_id") or "").strip()

            # Create a global profile (admin only).
            profile_upsert, _ = self._call(
                "actor_profile_upsert",
                {
                    "by": "user",
                    "caller_id": "",
                    "is_admin": True,
                    "profile": {
                        "id": "global-prof",
                        "name": "Global Profile",
                        "scope": "global",
                        "runtime": "custom",
                        "runner": "headless",
                        "command": [],
                        "submit": "newline",
                    },
                },
            )
            self.assertTrue(profile_upsert.ok, getattr(profile_upsert, "error", None))

            # Add secrets to the global profile.
            secret_update, _ = self._call(
                "actor_profile_secret_update",
                {
                    "by": "user",
                    "profile_id": "global-prof",
                    "caller_id": "",
                    "is_admin": True,
                    "set": {"GLOBAL_KEY": "global-secret"},
                },
            )
            self.assertTrue(secret_update.ok, getattr(secret_update, "error", None))

            attach, _ = self._call("attach", {"group_id": group_id, "path": ".", "by": "user"})
            self.assertTrue(attach.ok, getattr(attach, "error", None))

            # Attach profile WITHOUT explicit profile_scope — should still persist "global".
            add, _ = self._call(
                "actor_add",
                {
                    "group_id": group_id,
                    "actor_id": "peer-g",
                    "runtime": "codex",
                    "runner": "headless",
                    "profile_id": "global-prof",
                    "by": "user",
                },
            )
            self.assertTrue(add.ok, getattr(add, "error", None))

            # Verify actor has explicit profile_scope persisted.
            group = load_group(group_id)
            assert group is not None
            actor = find_actor(group, "peer-g")
            assert actor is not None
            self.assertEqual(str(actor.get("profile_id") or ""), "global-prof")
            self.assertEqual(str(actor.get("profile_scope") or ""), "global")

            # Simulate start: resolve should succeed via explicit ref, not caller-based fallback.
            resolved = resolve_linked_actor_before_start(
                group,
                "peer-g",
                get_actor_profile=get_actor_profile,
                load_actor_profile_secrets=load_actor_profile_secrets,
                update_actor_private_env=update_actor_private_env,
                caller_id="",
                is_admin=False,
            )
            self.assertIsInstance(resolved, dict)
            self.assertEqual(str(resolved.get("runtime") or ""), "custom")
            self.assertEqual(str(resolved.get("profile_scope") or ""), "global")
        finally:
            cleanup()

    def test_user_scope_profile_start_resolves_via_explicit_ref(self) -> None:
        """User-scope profile start resolves via explicit ref persisted at attach time."""
        home, cleanup = self._with_home()
        try:
            from cccc.daemon.actors.actor_profile_runtime import resolve_linked_actor_before_start
            from cccc.daemon.actors.actor_profile_store import get_actor_profile, load_actor_profile_secrets
            from cccc.daemon.actors.private_env_ops import update_actor_private_env
            from cccc.kernel.actors import find_actor
            from cccc.kernel.group import load_group

            create, _ = self._call("group_create", {"title": "user-start", "topic": "", "by": "user"})
            self.assertTrue(create.ok, getattr(create, "error", None))
            group_id = str((create.result or {}).get("group_id") or "").strip()

            # Create a user-scope profile.
            profile_upsert, _ = self._call(
                "actor_profile_upsert",
                {
                    "by": "user",
                    "caller_id": "user-b",
                    "is_admin": False,
                    "profile": {
                        "id": "user-prof",
                        "name": "User Profile",
                        "scope": "user",
                        "owner_id": "user-b",
                        "runtime": "custom",
                        "runner": "headless",
                        "command": [],
                        "submit": "newline",
                    },
                },
            )
            self.assertTrue(profile_upsert.ok, getattr(profile_upsert, "error", None))

            # Add secrets.
            secret_update, _ = self._call(
                "actor_profile_secret_update",
                {
                    "by": "user",
                    "profile_id": "user-prof",
                    "profile_scope": "user",
                    "profile_owner": "user-b",
                    "caller_id": "user-b",
                    "is_admin": False,
                    "set": {"USER_KEY": "user-b-secret"},
                },
            )
            self.assertTrue(secret_update.ok, getattr(secret_update, "error", None))

            attach, _ = self._call("attach", {"group_id": group_id, "path": ".", "by": "user"})
            self.assertTrue(attach.ok, getattr(attach, "error", None))

            # Attach with explicit user-scope ref.
            add, _ = self._call(
                "actor_add",
                {
                    "group_id": group_id,
                    "actor_id": "peer-u",
                    "runtime": "codex",
                    "runner": "headless",
                    "profile_id": "user-prof",
                    "profile_scope": "user",
                    "profile_owner": "user-b",
                    "caller_id": "user-b",
                    "is_admin": False,
                    "by": "user",
                },
            )
            self.assertTrue(add.ok, getattr(add, "error", None))

            # Verify persisted ref.
            group = load_group(group_id)
            assert group is not None
            actor = find_actor(group, "peer-u")
            assert actor is not None
            self.assertEqual(str(actor.get("profile_scope") or ""), "user")
            self.assertEqual(str(actor.get("profile_owner") or ""), "user-b")

            # Start resolve: explicit ref should stably hit user-scope profile.
            resolved = resolve_linked_actor_before_start(
                group,
                "peer-u",
                get_actor_profile=get_actor_profile,
                load_actor_profile_secrets=load_actor_profile_secrets,
                update_actor_private_env=update_actor_private_env,
                caller_id="user-b",
                is_admin=False,
            )
            self.assertIsInstance(resolved, dict)
            self.assertEqual(str(resolved.get("runtime") or ""), "custom")
            self.assertEqual(str(resolved.get("profile_scope") or ""), "user")
            self.assertEqual(str(resolved.get("profile_owner") or ""), "user-b")
        finally:
            cleanup()


    def test_legacy_bare_profile_id_resolves_as_global_only_in_resolver(self) -> None:
        """Actor with bare profile_id (no profile_scope/profile_owner) resolves via
        legacy compat in _resolve_profile_for_start only — actor_profile_ref() must
        return None so the implicit-global semantic does not leak to other helpers."""
        home, cleanup = self._with_home()
        try:
            from cccc.daemon.actors.actor_profile_runtime import (
                actor_profile_ref,
                resolve_linked_actor_before_start,
            )
            from cccc.daemon.actors.actor_profile_store import get_actor_profile, load_actor_profile_secrets
            from cccc.daemon.actors.private_env_ops import update_actor_private_env
            from cccc.kernel.actors import find_actor, update_actor
            from cccc.kernel.group import load_group

            create, _ = self._call("group_create", {"title": "legacy-test", "topic": "", "by": "user"})
            self.assertTrue(create.ok, getattr(create, "error", None))
            group_id = str((create.result or {}).get("group_id") or "").strip()

            # Create a global profile.
            profile_upsert, _ = self._call(
                "actor_profile_upsert",
                {
                    "by": "user",
                    "caller_id": "",
                    "is_admin": True,
                    "profile": {
                        "id": "legacy-prof",
                        "name": "Legacy Profile",
                        "scope": "global",
                        "runtime": "custom",
                        "runner": "headless",
                        "command": [],
                        "submit": "newline",
                    },
                },
            )
            self.assertTrue(profile_upsert.ok, getattr(profile_upsert, "error", None))

            attach, _ = self._call("attach", {"group_id": group_id, "path": ".", "by": "user"})
            self.assertTrue(attach.ok, getattr(attach, "error", None))

            # Add actor normally (this will persist explicit scope).
            add, _ = self._call(
                "actor_add",
                {
                    "group_id": group_id,
                    "actor_id": "legacy-peer",
                    "runtime": "codex",
                    "runner": "headless",
                    "profile_id": "legacy-prof",
                    "by": "user",
                },
            )
            self.assertTrue(add.ok, getattr(add, "error", None))

            # Simulate legacy data: strip profile_scope/profile_owner from the actor,
            # leaving only bare profile_id.
            group = load_group(group_id)
            assert group is not None
            actor = find_actor(group, "legacy-peer")
            assert actor is not None
            actor.pop("profile_scope", None)
            actor.pop("profile_owner", None)
            group.save()

            # Verify actor_profile_ref returns None for bare profile_id — no implicit global.
            reloaded = load_group(group_id)
            assert reloaded is not None
            legacy_actor = find_actor(reloaded, "legacy-peer")
            assert legacy_actor is not None
            self.assertIsNone(actor_profile_ref(legacy_actor))

            # But resolve_linked_actor_before_start still works via legacy compat.
            resolved = resolve_linked_actor_before_start(
                reloaded,
                "legacy-peer",
                get_actor_profile=get_actor_profile,
                load_actor_profile_secrets=load_actor_profile_secrets,
                update_actor_private_env=update_actor_private_env,
                caller_id="",
                is_admin=False,
            )
            self.assertIsInstance(resolved, dict)
            self.assertEqual(str(resolved.get("runtime") or ""), "custom")
            # After start resolution, the actor should now have explicit scope persisted
            # (the resolver writes it back via apply_profile_link_to_actor).
            final_group = load_group(group_id)
            assert final_group is not None
            final_actor = find_actor(final_group, "legacy-peer")
            assert final_actor is not None
            self.assertEqual(str(final_actor.get("profile_scope") or ""), "global")
        finally:
            cleanup()


    def test_only_active_group_actors_recovered(self) -> None:
        """FIX-11: daemon start only recovers actors for the active group."""
        home, cleanup = self._with_home()
        try:
            from cccc.kernel.active import set_active_group_id
            from cccc.kernel.group import load_group

            # Create two groups
            create1, _ = self._call("group_create", {"title": "active-grp", "topic": "", "by": "user"})
            self.assertTrue(create1.ok)
            active_gid = str((create1.result or {}).get("group_id") or "").strip()

            create2, _ = self._call("group_create", {"title": "inactive-grp", "topic": "", "by": "user"})
            self.assertTrue(create2.ok)
            inactive_gid = str((create2.result or {}).get("group_id") or "").strip()

            # Mark both as running with active scopes
            for gid in (active_gid, inactive_gid):
                attach, _ = self._call("attach", {"group_id": gid, "path": ".", "by": "user"})
                self.assertTrue(attach.ok)
                g = load_group(gid)
                assert g is not None
                g.doc["running"] = True
                g.save()

            # Set only one as the active group
            set_active_group_id(active_gid)

            started_groups: list[str] = []

            orig_list_actors = __import__("cccc.kernel.actors", fromlist=["list_actors"]).list_actors

            def _tracking_list_actors(group):
                started_groups.append(group.group_id)
                return []  # no actors to start

            with patch("cccc.daemon.group.bootstrap_actor_ops.list_actors", side_effect=_tracking_list_actors):
                autostart_running_groups(
                    home,
                    effective_runner_kind=lambda runner: runner,
                    find_scope_url=lambda _group, _scope_key: str(Path(".").resolve()),
                    supported_runtimes=("codex",),
                    ensure_mcp_installed=lambda _runtime, _cwd: True,
                    auto_mcp_runtimes=("codex",),
                    pty_supported=lambda: True,
                    merge_actor_env_with_private=lambda _gid, _aid, env: dict(env),
                    inject_actor_context_env=lambda env, _gid, _aid: dict(env),
                    prepare_pty_env=lambda env: dict(env),
                    normalize_runtime_command=lambda _runtime, command: list(command),
                    pty_backlog_bytes=lambda: 1024,
                    write_headless_state=lambda _gid, _aid: None,
                    write_pty_state=lambda _gid, _aid, _pid: None,
                    clear_preamble_sent=lambda _group, _aid: None,
                    throttle_reset_actor=lambda _gid, _aid: None,
                    automation_on_resume=lambda _group: None,
                    get_group_state=lambda _group: "idle",
                )

            # Only the active group should have been processed
            self.assertIn(active_gid, started_groups, "Active group should be recovered")
            self.assertNotIn(inactive_gid, started_groups, "Inactive group should be skipped")
        finally:
            cleanup()

    def test_empty_active_group_recovers_all(self) -> None:
        """FIX-11 fallback: when active_group_id is empty, recover all running groups."""
        home, cleanup = self._with_home()
        try:
            from cccc.kernel.active import active_path
            from cccc.kernel.group import load_group
            from cccc.util.fs import atomic_write_json

            # Create one running group
            create, _ = self._call("group_create", {"title": "fallback-grp", "topic": "", "by": "user"})
            self.assertTrue(create.ok)
            gid = str((create.result or {}).get("group_id") or "").strip()

            attach, _ = self._call("attach", {"group_id": gid, "path": ".", "by": "user"})
            self.assertTrue(attach.ok)
            g = load_group(gid)
            assert g is not None
            g.doc["running"] = True
            g.save()

            # Set empty active_group_id
            atomic_write_json(active_path(), {"v": 1, "active_group_id": ""})

            started_groups: list[str] = []

            def _tracking_list_actors(group):
                started_groups.append(group.group_id)
                return []

            with patch("cccc.daemon.group.bootstrap_actor_ops.list_actors", side_effect=_tracking_list_actors):
                autostart_running_groups(
                    home,
                    effective_runner_kind=lambda runner: runner,
                    find_scope_url=lambda _group, _scope_key: str(Path(".").resolve()),
                    supported_runtimes=("codex",),
                    ensure_mcp_installed=lambda _runtime, _cwd: True,
                    auto_mcp_runtimes=("codex",),
                    pty_supported=lambda: True,
                    merge_actor_env_with_private=lambda _gid, _aid, env: dict(env),
                    inject_actor_context_env=lambda env, _gid, _aid: dict(env),
                    prepare_pty_env=lambda env: dict(env),
                    normalize_runtime_command=lambda _runtime, command: list(command),
                    pty_backlog_bytes=lambda: 1024,
                    write_headless_state=lambda _gid, _aid: None,
                    write_pty_state=lambda _gid, _aid, _pid: None,
                    clear_preamble_sent=lambda _group, _aid: None,
                    throttle_reset_actor=lambda _gid, _aid: None,
                    automation_on_resume=lambda _group: None,
                    get_group_state=lambda _group: "idle",
                )

            # Should recover all groups when active_group_id is empty
            self.assertIn(gid, started_groups, "Should recover all when active_group_id is empty")
        finally:
            cleanup()


if __name__ == "__main__":
    unittest.main()
