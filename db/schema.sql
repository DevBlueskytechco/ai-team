create table if not exists runs (
  id serial primary key, agent text not null, ticket text not null, task_type text, agent_version text, model text,
  tokens integer, cost_usd numeric(10,4), turns integer, started_at timestamptz, is_error boolean default false
);
create table if not exists reviews (
  id serial primary key, agent text, ticket text, label text, scores jsonb, reviewer text, reviewed_at date, agent_version text
);
-- Dashboard
create or replace view v_cost_by_agent_day as
  select agent, date(started_at) d, sum(cost_usd) cost, sum(tokens) tokens, count(*) runs, avg(turns) avg_turns from runs group by 1,2;
create or replace view v_pass_rate_14d as
  select agent, count(*) n, round(100.0*sum(case when label in ('dat','sua_nhe') then 1 else 0 end)/count(*),1) pct_dat_sua_nhe
  from reviews where reviewed_at >= current_date - 14 group by 1;
create or replace view v_month_budget as
  select to_char(started_at,'YYYY-MM') m, sum(cost_usd) spent, round(100*sum(cost_usd)/2000,1) pct from runs group by 1;
