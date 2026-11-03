-- Batch 1 (t98u): real sign-in. Platform accounts (admin / member) and server-side sessions.
-- Actor columns elsewhere stay text and now carry the user name.

CREATE TABLE app_user (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  username text NOT NULL UNIQUE CHECK (username ~ '^[a-z0-9][a-z0-9._-]{1,31}$'),
  display_name text NOT NULL DEFAULT '',
  password_hash text,                              -- argon2id; NULL = no password sign-in (launcher ticket only)
  role text NOT NULL DEFAULT 'member' CHECK (role IN ('admin', 'member')),
  is_active boolean NOT NULL DEFAULT true,
  must_change_password boolean NOT NULL DEFAULT false,
  failed_logins integer NOT NULL DEFAULT 0,
  locked_until timestamptz,
  password_changed_at timestamptz,
  last_login_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE app_session (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  token_hash bytea NOT NULL UNIQUE,                -- sha256 of the cookie value; the value itself is never stored
  csrf_token text NOT NULL,
  user_id uuid NOT NULL REFERENCES app_user(id) ON DELETE CASCADE,
  created_at timestamptz NOT NULL DEFAULT now(),
  last_seen_at timestamptz NOT NULL DEFAULT now(),
  expires_at timestamptz NOT NULL,
  revoked_at timestamptz,
  ip text,
  user_agent text
);
CREATE INDEX app_session_user_idx ON app_session (user_id) WHERE revoked_at IS NULL;
