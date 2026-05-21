create table if not exists users (
    id text primary key,
    telegram_id integer not null unique,
    username text,
    first_name text,
    role text not null default 'guest',
    is_admin integer not null default 0,
    created_at text not null
);

create table if not exists restaurants (
    id text primary key,
    title text not null,
    slug text not null unique,
    description text,
    is_active integer not null default 1,
    created_by_user_id text not null references users(id),
    created_at text not null
);

create table if not exists branches (
    id text primary key,
    franchise_id text not null references restaurants(id) on delete cascade,
    title text not null,
    address text,
    phone text,
    is_active integer not null default 1,
    position integer not null default 0,
    created_at text not null
);

create table if not exists categories (
    id text primary key,
    branch_id text not null references branches(id) on delete cascade,
    title text not null,
    position integer not null default 0,
    is_active integer not null default 1,
    created_at text not null
);

create table if not exists dishes (
    id text primary key,
    branch_id text not null references branches(id) on delete cascade,
    category_id text not null references categories(id) on delete cascade,
    title text not null,
    description text,
    price integer,
    weight text,
    photo_file_id text,
    is_active integer not null default 1,
    position integer not null default 0,
    created_at text not null
);

create table if not exists app_state (
    key text primary key,
    value text not null
);

create table if not exists admin_invites (
    id text primary key,
    token_hash text not null unique,
    role text not null default 'admin',
    created_by_user_id text not null references users(id),
    used_by_user_id text references users(id),
    expires_at text not null,
    used_at text,
    created_at text not null
);

create index if not exists idx_branches_franchise on branches(franchise_id, position);
create index if not exists idx_categories_branch on categories(branch_id, position);
create index if not exists idx_dishes_category on dishes(category_id, position);

create table if not exists admin_sessions (
    telegram_id integer primary key,
    chat_id integer not null,
    state text,
    draft_json text not null default '{}',
    history_json text not null default '[]',
    updated_at text not null
);

create index if not exists idx_admin_invites_token on admin_invites(token_hash);
