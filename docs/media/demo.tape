# Records docs/media/demo.gif from the real output of a benchmark run (demo-run.txt), replayed by replay.py:
#   vhs docs/media/demo.tape
Output docs/media/demo.gif
Set Shell "bash"
Set FontSize 14
Set Width 1240
Set Height 720
Set Padding 18
Set Theme "Catppuccin Mocha"
Set TypingSpeed 30ms

Hide
Type "export PS1='$ ' && hive() { python3 docs/media/replay.py; } && clear"
Enter
Show

Type `hive "Add a combo discount (a coffee makes one croissant half price) and buy-3-pay-2 muffins" \`
Enter
Type `  --done "python3 -m unittest discover -s acceptance -t ."`
Sleep 500ms
Enter
Sleep 25s
Sleep 5s
