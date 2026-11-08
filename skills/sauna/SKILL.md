---
name: sauna
description: Control the local SaunaBox Solara heater with the validated sauna tools.
---

# Sauna

Use only these tools: `sauna_status`, `sauna_preheat`, `sauna_off`, `sauna_set_temperature`, and `sauna_set_timer`.

The heater accepts 77°F to 158°F and 1 to 90 minutes. Do not call a tool with a value outside those limits. Tell the user the limit.

If the user gives no temperature unit, the unit is Fahrenheit. If the user gives Celsius, pass `temperature_c` and omit `temperature_f`. The tool converts Celsius. Pass hours as minutes. 1 hour is 60 minutes. 1.5 hours is 90 minutes.

Use `sauna_preheat` when the user wants the sauna turned on with a temperature and a timer. Call it once. Do not call a second power command.

Use `sauna_set_temperature` or `sauna_set_timer` only when the sauna is already on. Use `sauna_off` to turn it off. Use `sauna_status` for the current target temperature and the remaining time.

The controller reports the target temperature. It does not report a measured cabin temperature. Do not invent a measured temperature.

Treat `confirmed: true` as success. Treat `confirmed: false` as not confirmed. Say the `error` text. If `status` is `unverified`, say that the command was not confirmed. Do not send the same power command again.

Ask a question only when the temperature or the duration is missing for a heat command. Do not choose a temperature or a duration for the user.
