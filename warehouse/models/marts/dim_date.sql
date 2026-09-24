-- Date dimension and MetricFlow time spine. It lives in marts (not intermediate) because compiled metric SQL may join it
-- and the agent's role can only read marts.
select
    date_day,
    week_start,
    week_end,
    iso_year,
    iso_week,
    month_start,
    month_index,
    fiscal_year,
    fiscal_year_label,
    fiscal_quarter,
    fiscal_quarter_label,
    fiscal_quarter_start,
    fiscal_quarter_end,
    is_complete_month,
    is_complete_week
from {{ ref('int_calendar') }}
