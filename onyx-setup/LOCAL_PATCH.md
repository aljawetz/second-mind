# Running a local Onyx Canvas connector patch

## Layout

```
onyx-patch/connector.py          # patched file (from v4.7.3 image)
onyx-data/deployment/
  docker-compose.yml             # managed by onyx-cli
  docker-compose.override.yml    # mounts the patch into api_server + background
```

## What the fix does

1. On `GET /courses/{id}/pages` → HTTP 404 (Pages tab disabled), Onyx used to
   skip the **entire course**. Now it only skips the **pages stage** and continues
   to assignments / announcements.
2. Per-course/stage HTTP 403 (common with student tokens) used to raise
   `InsufficientPermissionsError` and mark the CC pair **INVALID**, blocking
   all further indexing. Now it skips that stage and continues.
3. Assignment fetches no longer request privileged includes
   (`assignment_visibility`, `overrides`) that 403 for student tokens.

## Apply / refresh after editing the patch

```bash
cd onyx-data/deployment
docker compose -p onyx-kingstown up -d --force-recreate --no-deps api_server background
```

## Re-test in the UI

1. Open http://localhost:3000 → Admin → Connectors → CMU (Canvas)
2. If status is INVALID, edit/reconnect credentials, then **Update** / re-index
3. Watch for failures: pages-disabled courses should now say
   `Canvas pages unavailable...` and still index assignments

## Notes

- Indexing runs in the **background** worker — both services must get the mount.
- `onyx-cli deploy upgrade` may rewrite compose files; re-check the override after upgrades.
- This does **not** yet index modules/files (where most CMU course content lives).
  That needs a larger connector change.
