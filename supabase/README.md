# Supabase integration

This directory exists so the Princess Supabase project can be connected to the GitHub repository with **Working directory `.`**.

## Deployment authority

Princess does **not** use Supabase SQL migrations as the database schema authority today.

The reviewed database migration source of truth remains:

```text
/migrations/versions/
/migrations/env.py
src/princess_app/adapters/postgres/migrate
```

Those Alembic revisions are applied with an explicit migration-role database URL. Do not copy them into
`supabase/migrations/` or introduce a second migration history without a separate reviewed migration-authority
decision.

For the Supabase Dashboard GitHub integration, keep:

```text
Repository:            HMarcusWH/YouAreASpecialLittlePrincess
Working directory:     .
Deploy to production:  OFF
Production branch:     main
```

The Supabase dashboard may label the primary hosted project branch as "PRODUCTION"; Princess currently treats this
connected project as the qualified staging/sandbox identity environment. That dashboard label does not widen the
Princess production/live authority recorded in the repository.

## What may be committed here

- `config.toml` and other reviewed non-secret Supabase project metadata.
- Future Edge Function or Storage configuration only after the owning task explicitly adopts it.

Never commit project refs, database passwords, Management API tokens, service-role/secret keys, user credentials,
JWTs, protected evidence files, or raw provider responses.

## Local state

Supabase CLI state and local secret files are ignored by `supabase/.gitignore`.

If GitHub-driven Supabase deployment is enabled later, reconcile it with the Alembic migration authority first.
Do not enable **Deploy to production** merely because this directory exists.
