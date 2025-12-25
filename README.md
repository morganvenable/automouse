This is a prototype automouse layer helper for Windows. When the mouse moves, it turns on an intercept which blocks the specified keys (F S D in my case) from the config.yaml file and instead outputs mouse clicks, as well as enabling Ctrl-X, Ctrl-C, and Ctrl-V on three keys south of there. 

To try the prototype clone the repo, go to the folder, and run:
pip install -r requirements.txt
python -m automouse

It'll put an icon in your taskbar to show it's running.
