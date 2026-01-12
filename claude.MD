<claude-instructions>

<principles>
  <style>No emojis. No em dashes - use hyphens or colons instead.</style>

  <epistemology>
    Assumptions are the enemy. Never guess numerical values - benchmark instead of estimating.
    When uncertain, measure. Say "this needs to be measured" rather than inventing statistics.
  </epistemology>

  <scaling>
    Validate at small scale before scaling up. Run a sub-minute version first to verify the
    full pipeline works. When scaling, only the scale parameter should change.
  </scaling>

  <interaction>
    Clarify unclear requests, then proceed autonomously. Only ask for help when scripts timeout
    (>2min), sudo is needed, or genuine blockers arise.
  </interaction>

  <ground-truth-clarification>
    For non-trivial tasks, reach ground truth understanding before coding. Simple tasks execute
    immediately. Complex tasks (refactors, new features, ambiguous requirements) require
    clarification first: research codebase, ask targeted questions, confirm understanding,
    persist the plan, then execute autonomously.
  </ground-truth-clarification>

  <first-principles-reimplementation>
    Building from scratch can beat adapting legacy code when implementations are in wrong
    languages, carry historical baggage, or need architectural rewrites. Understand domain
    at spec level, choose optimal stack, implement incrementally with human verification.
  </first-principles-reimplementation>

  <constraint-persistence>
    When user defines constraints ("never X", "always Y", "from now on"), immediately persist
    to project's local CLAUDE.md. Acknowledge, write, confirm.
  </constraint-persistence>
</principles>

<mcp>
  Use MCP servers for external info before guessing. exa: web search, code examples.
  context7: library docs (resolve-library-id first, then query-docs).
</mcp>

<deployment>
  CRITICAL RULES - VIOLATING THESE WASTES TIME AND MONEY:

  1. NEVER use DigitalOcean API destructive actions (power_cycle, rebuild, restore, etc.)
  2. NEVER restart/reboot the droplet - it can wipe the setup
  3. NEVER reinstall pip packages unless there's a specific error requiring it
  4. NEVER rebuild or redeploy from scratch - only pull and restart

  TO DEPLOY UPDATES (the ONLY correct method):
  ssh -i ~/.ssh/sadhuastro_key root@170.64.142.252 \
    "cd /root/brain_agent && git pull && systemctl restart brain-agent"

  Server: 170.64.142.252
  SSH Key: ~/.ssh/sadhuastro_key (NOT id_ed25519)
  Service: brain-agent.service (systemd, not Docker)

  If SSH fails, ASK THE USER - do not try to "fix" it with API actions.
</deployment>

<security>
  Only port 22 (SSH) should be open. No other ports.
  Verify with: ss -tlnp
  Bot uses outbound polling only - no inbound ports needed.
</security>

</claude-instructions>
