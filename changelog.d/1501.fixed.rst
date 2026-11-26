Fixed a path-like ``command`` passed to ``run_process()`` or ``open_process()`` being
executed through the shell, allowing command injection via shell metacharacters in the
path
