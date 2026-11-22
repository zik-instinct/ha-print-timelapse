# UI test harness

Playwright-driven end-to-end tests against a local throwaway Home Assistant
instance. Credentials are read from the environment and are never committed:

    export HA_TEST_USER=... HA_TEST_PASS=...

`hatest.sh` starts/stops the local stack; the three scripts cover the config
flow, the options flow and card rendering on a classic Lovelace dashboard.
