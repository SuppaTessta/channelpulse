{#- Use the configured schema name as-is (staging / intermediate / marts) instead of dbt's default
    "<target>_<custom>" prefixing: the agent's read-only role is granted exactly the `marts` schema. -#}
{% macro generate_schema_name(custom_schema_name, node) -%}
    {{ custom_schema_name if custom_schema_name is not none else target.schema }}
{%- endmacro %}
