"""raft status: where a study stands, one line per gate, and the one command to run next."""


def prepare_cmd(study: str, agent: str | None = None, attacker: str | None = None) -> str:
    if not agent:
        return f"uv run raft prepare --study {study} --agent <claude-code|codex>"
    cmd = f"uv run raft prepare --study {study} --agent {agent}" + (' --cmd "…"' if agent == "command" else "")
    if attacker and attacker != agent:
        cmd += f" --attacker {attacker}" + (' --attacker-cmd "…"' if attacker == "command" else "")
    return cmd
