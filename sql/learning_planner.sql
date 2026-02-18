-- Run in Supabase SQL editor

create extension if not exists pgcrypto;

create table if not exists public.course_plans (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null,
  document_id uuid null,
  title text not null,
  overview text,
  start_date date not null,
  duration_days int not null check (duration_days between 7 and 90),
  created_at timestamptz not null default now()
);

create index if not exists idx_course_plans_user_created_at
  on public.course_plans (user_id, created_at desc);

create table if not exists public.course_modules (
  id uuid primary key default gen_random_uuid(),
  course_id uuid not null references public.course_plans(id) on delete cascade,
  user_id uuid not null,
  day_index int not null check (day_index > 0),
  task_date date not null,
  title text not null,
  lesson_content text,
  practice_content text,
  quiz_content text,
  created_at timestamptz not null default now()
);

create index if not exists idx_course_modules_user_date
  on public.course_modules (user_id, task_date);

create index if not exists idx_course_modules_course_day
  on public.course_modules (course_id, day_index);

create table if not exists public.saved_quizzes (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null,
  title text not null,
  content text not null,
  source_course_id uuid null references public.course_plans(id) on delete set null,
  source_module_id uuid null references public.course_modules(id) on delete set null,
  created_at timestamptz not null default now()
);

create index if not exists idx_saved_quizzes_user_created_at
  on public.saved_quizzes (user_id, created_at desc);

-- Optional: if your project uses RLS, enable and add policies
alter table public.course_plans enable row level security;
alter table public.course_modules enable row level security;
alter table public.saved_quizzes enable row level security;

drop policy if exists "course_plans_owner_all" on public.course_plans;
create policy "course_plans_owner_all"
  on public.course_plans
  for all
  using (auth.uid() = user_id)
  with check (auth.uid() = user_id);

drop policy if exists "course_modules_owner_all" on public.course_modules;
create policy "course_modules_owner_all"
  on public.course_modules
  for all
  using (auth.uid() = user_id)
  with check (auth.uid() = user_id);

drop policy if exists "saved_quizzes_owner_all" on public.saved_quizzes;
create policy "saved_quizzes_owner_all"
  on public.saved_quizzes
  for all
  using (auth.uid() = user_id)
  with check (auth.uid() = user_id);
