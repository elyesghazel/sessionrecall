# Demo

Everything in the README's GIF and screenshots comes from this folder. The sessions in
`corpus/` are made up: 14 sessions across Claude Code, Codex and OpenCode about a Rust
CLI (`tally`), a React shop (`shopfront`), a billing API, a notes app and some infra.
No real transcript is involved.

```sh
python3 demo/build_corpus.py   # regenerate corpus/ after editing the sessions in it
source demo/env.sh             # a shell whose HOME is the corpus (default /tmp/sessionrecall-demo)
recall why did we drop the admin dashboard

vhs demo/demo.tape             # docs/demo.gif (needs vhs, ttyd, ffmpeg)
vhs demo/screenshots.tape      # docs/*.png
```

`bin/demo-agent` stands in for a coding agent: its MCP call to `recall mcp` is real, the
sentences around it are fixed so the recording does not need a model or an account.
