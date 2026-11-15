# The PNG screenshots in docs/. Same synthetic corpus as demo.tape.
#
#     vhs demo/screenshots.tape   # from the repo root

Output "/tmp/agentrecall-demo-screenshots.gif"

Set Shell bash
Set FontFamily "JetBrainsMono Nerd Font"
Set FontSize 15
Set Width 1400
Set Height 410
Set Padding 24
Set Theme "Catppuccin Mocha"
Set TypingSpeed 5ms
Set CursorBlink false

Hide
Type "source demo/env.sh && recall --index && export PS1='\[\e[35m\]$\[\e[0m\] ' && clear"
Enter
Sleep 4s

Hide
Type "clear"
Enter
Show
Type "recall -n 2 why did we drop the admin dashboard"
Enter
Sleep 3s
Screenshot docs/search.png
Sleep 1s

Hide
Type "clear"
Enter
Show
Type "recall --agent codex -n 2 test fails randomly on CI"
Enter
Sleep 3s
Screenshot docs/agent-filter.png
Sleep 1s

Hide
Type "clear"
Enter
Show
Type "demo-agent"
Enter
Sleep 7s
Screenshot docs/mcp.png
Sleep 1s

Sleep 1s
