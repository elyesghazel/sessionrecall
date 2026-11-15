# The README demo. Runs against the synthetic corpus in demo/corpus only.
#
#     vhs demo/demo.tape          # from the repo root; writes docs/demo.gif
#
# Needs vhs, ttyd and ffmpeg. demo/env.sh sets up the fake HOME.

Output docs/demo.gif

Set Shell bash
Set FontFamily "JetBrainsMono Nerd Font"
Set FontSize 15
Set Width 1400
Set Height 780
Set Padding 24
Set Theme "Catppuccin Mocha"
Set TypingSpeed 22ms
Set CursorBlink false

Hide
Type "source demo/env.sh && recall --index && export PS1='\[\e[35m\]$\[\e[0m\] ' && clear"
Enter
Sleep 4s
Show

Type "recall install claude --print --no-hook"
Sleep 300ms
Enter
Sleep 3.5s

Hide
Type "clear"
Enter
Show
Type "recall -n 2 why did we drop the admin dashboard"
Sleep 300ms
Enter
Sleep 4s

Type "recall --agent codex -n 1 test fails randomly on CI"
Sleep 300ms
Enter
Sleep 3.5s

Hide
Type "clear"
Enter
Show
Type "recall --show b5ecb9e6 --digest"
Sleep 300ms
Enter
Sleep 3s

Hide
Type "clear"
Enter
Show
Type "demo-agent   # an agent calling recall over MCP"
Sleep 300ms
Enter
Sleep 7s
