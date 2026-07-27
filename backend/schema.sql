-- Reddit Scanner schema
-- Run this in the Supabase SQL editor (Project -> SQL Editor -> New query)

create extension if not exists "uuid-ossp";

-- ---------- Companies (tenants) ----------
create table if not exists companies (
    id uuid primary key default uuid_generate_v4(),
    name text not null,
    product_description text,
    plan_tier text not null default 'trial',
    created_at timestamptz not null default now()
);

-- ---------- Scanner configs (one company can run multiple, mixed modes) ----------
create table if not exists scanner_configs (
    id uuid primary key default uuid_generate_v4(),
    company_id uuid not null references companies(id) on delete cascade,
    mode text not null check (mode in ('content', 'competitor')),
    subreddits text[] not null default '{}',
    keywords text[] not null default '{}',
    competitors text[] not null default '{}',   -- only used by competitor mode
    min_score_threshold numeric not null default 0.6,
    is_active boolean not null default true,
    created_at timestamptz not null default now()
);

-- ---------- Raw ingested + pre-filtered posts (shared by both modes) ----------
create table if not exists posts (
    id uuid primary key default uuid_generate_v4(),
    reddit_id text not null unique,
    subreddit text not null,
    author_username text,
    title text,
    body text,
    url text,
    created_at timestamptz not null,
    ingested_at timestamptz not null default now()
);

create index if not exists idx_posts_subreddit on posts(subreddit);
create index if not exists idx_posts_created_at on posts(created_at);

-- ---------- Content Mode output ----------
create table if not exists content_matches (
    id uuid primary key default uuid_generate_v4(),
    post_id uuid not null references posts(id) on delete cascade,
    config_id uuid not null references scanner_configs(id) on delete cascade,
    intent_score numeric not null,
    ai_reasoning text,
    sent_in_digest boolean not null default false,
    created_at timestamptz not null default now()
);

create index if not exists idx_content_matches_config on content_matches(config_id);
create index if not exists idx_content_matches_digest on content_matches(sent_in_digest);

-- ---------- Competitor Mode output ----------
create table if not exists leads (
    id uuid primary key default uuid_generate_v4(),
    reddit_username text not null,
    company_id uuid not null references companies(id) on delete cascade,
    first_seen timestamptz not null default now(),
    last_seen timestamptz not null default now(),
    aggregate_score numeric not null default 0,
    status text not null default 'new' check (status in ('new', 'reviewed', 'contacted', 'dismissed')),
    unique(reddit_username, company_id)
);

create table if not exists lead_signals (
    id uuid primary key default uuid_generate_v4(),
    lead_id uuid not null references leads(id) on delete cascade,
    post_id uuid not null references posts(id) on delete cascade,
    competitor_mentioned text,
    pain_point text,
    switch_intent boolean not null default false,
    ai_reasoning text,
    created_at timestamptz not null default now()
);

create index if not exists idx_lead_signals_lead on lead_signals(lead_id);
